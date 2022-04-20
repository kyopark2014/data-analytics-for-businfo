import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';

import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as kinesisstream from 'aws-cdk-lib/aws-kinesis';
import * as kinesisfirehose from 'aws-cdk-lib/aws-kinesisfirehose';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as cfn from 'aws-cdk-lib/aws-cloudformation';
import * as logs from 'aws-cdk-lib/aws-logs'

import * as glue from 'aws-cdk-lib/aws-glue'
import * as athena from 'aws-cdk-lib/aws-athena'

export class CdkStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);
    
    // S3
    const s3Bucket = new s3.Bucket(this, "cdk-businfo",{
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      publicReadAccess: false,
      versioned: false,
    });
    new cdk.CfnOutput(this, 'bucketName', {
      value: s3Bucket.bucketName,
      description: 'The nmae of bucket',
    });
    new cdk.CfnOutput(this, 's3Arn', {
      value: s3Bucket.bucketArn,
      description: 'The arn of s3',
    });
    new cdk.CfnOutput(this, 's3Path', {
      value: 's3://'+s3Bucket.bucketName,
      description: 'The path of s3',
    });

    // kinesis data stream
    const stream = new kinesisstream.Stream(this, 'Stream', {
      streamName: 'businfo',
      retentionPeriod: cdk.Duration.hours(48),
      streamMode: kinesisstream.StreamMode.ON_DEMAND
    });

    new cdk.CfnOutput(this, 'StreamARN', {
      value: stream.streamArn,
      description: 'The arn of kinesis stream',
    });

    // using pre-defined metric method
    stream.metricGetRecordsSuccess();
    stream.metricPutRecordSuccess();

    // DynamoDB
    const tableName = 'dynamodb-businfo';
    const dataTable = new dynamodb.Table(this, 'dynamodb-businfo', {
        tableName: tableName,
        partitionKey: { name: 'RouteId', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'Timestamp', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        // readCapacity: 1,
        // writeCapacity: 1,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        //timeToLiveAttribute: 'ttl',
        kinesisStream: stream,
    });

    // Lambda - kinesisInfo
    const lambdakinesis = new lambda.Function(this, "LambdaKinesisStream", {
      description: 'get eventinfo from kinesis data stream',
      runtime: lambda.Runtime.NODEJS_14_X, 
      code: lambda.Code.fromAsset("repositories/lambda-kinesis-stream"), 
      handler: "index.handler", 
      timeout: cdk.Duration.seconds(3),
      environment: {
      }
    }); 

    // Lambda - kinesisInfo
    const lambdafirehose = new lambda.Function(this, "LimbdaKinesisFirehose", {
      description: 'update event sources',
      runtime: lambda.Runtime.NODEJS_14_X, 
      code: lambda.Code.fromAsset("repositories/lambda-kinesis-firehose"), 
      handler: "index.handler", 
      timeout: cdk.Duration.seconds(3),
      environment: {
      }
    }); 
    new cdk.CfnOutput(this, 'LambdaKinesisARN', {
      value: lambdafirehose.functionArn,
      description: 'The arn of lambda for kinesis',
    });

    // connect lambda for kinesis with kinesis data stream
    const eventSource = new lambdaEventSources.KinesisEventSource(stream, {
      startingPosition: lambda.StartingPosition.TRIM_HORIZON,
    });
    lambdakinesis.addEventSource(eventSource);    

    // Lambda - UpdateBusInfo
    const lambdaBusInfo = new lambda.Function(this, "LambdaBusInfo", {
      runtime: lambda.Runtime.NODEJS_14_X, 
      code: lambda.Code.fromAsset("repositories/lambda-businfo"), 
      handler: "index.handler", 
      timeout: cdk.Duration.seconds(10),
      environment: {
        tableName: tableName,
      }
    });  
    dataTable.grantReadWriteData(lambdaBusInfo);

    const rule = new events.Rule(this, 'Cron', {
      description: "Schedule a Lambda to save arrival time of buses",
      schedule: events.Schedule.expression('rate(1 minute)'),
    }); 
    rule.addTarget(new targets.LambdaFunction(lambdaBusInfo));

    // To convert record format
    const parquetRole = new iam.Role(this, "ParquetRole", {
      assumedBy: new iam.ServicePrincipal("glue.amazonaws.com"),
      description: "Role for parquet translation",
      inlinePolicies: {
        'allow-convert-json-to-parquet': 
          new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  "s3:AbortMultipartUpload",
                  "s3:GetBucketLocation",
                  "s3:GetObject",
                  "s3:ListBucket",
                  "s3:ListBucketMultipartUploads",
                  "s3:PutObject"
                ],
                resources: [
                  s3Bucket.bucketArn,
                  s3Bucket.bucketArn + "/*"
                ]
              }), 
              new iam.PolicyStatement({  
                effect: iam.Effect.ALLOW,
                actions: [
                  "glue:GetTable",
                  "glue:GetTableVersion",
                  "glue:GetTableVersions"
                ],
                resources: ['*'],
              }),  
              new iam.PolicyStatement({  
                effect: iam.Effect.ALLOW,
                actions: [
                  "firehose:DeleteDeliveryStream",
                  "firehose:PutRecord",
                  "firehose:PutRecordBatch",
                  "firehose:UpdateDestination"
                ],
                resources: ['*'],
              }), 
            ]
          })
      },
      managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSGlueServiceRole"),
      ],
    });
    new cdk.CfnOutput(this, 'parquetRoleArn', {
      value: parquetRole.roleArn,
      description: 'The arn of parquetRole',
    });
    
    const databaseName = "inspector";
    const crawler = new glue.CfnCrawler(this, "TranslateToParquetGlueCrawler", {
      name: "translate-parquet-crawler",
      role: parquetRole.roleArn,
      targets: {
          s3Targets: [
              {path: 's3://'+s3Bucket.bucketName}, 
          ]
      },
      databaseName: databaseName,
      schemaChangePolicy: {
          deleteBehavior: 'DELETE_FROM_DATABASE'
      },      
    });

    // To-Do: how to run crawler trigger
  /*  new glue.CfnTrigger(this, 'CrawlerTrigger', {
      name: 'crawler-trigger',
      type: 'CONDITIONAL',
      description: 'Run crawler',
      actions: [
        {
          crawlerName: crawler.name,
        },
      ],
      startOnCreation: true,
      predicate: {
        logical: 'AND',
        conditions: [
          {
            logicalOperator: 'EQUALS',
            jobName: 'crawler',
            state: 'SUCCEEDED',
          }
        ], 
      }, 
    }); */

    const firehoseRole = new iam.Role(this, 'TranslationRole', {
      assumedBy: new iam.ServicePrincipal('firehose.amazonaws.com'),
      inlinePolicies: {
        'allow-lambda-translation': new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  "kinesis:DescribeStream",
                  "kinesis:DescribeStreamSummary",
                  "kinesis:GetRecords",
                  "kinesis:GetShardIterator",
                  "kinesis:ListShards",
                  "kinesis:SubscribeToShard"
                ],
                resources: [stream.streamArn]
              }),
              new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  "s3:AbortMultipartUpload",
                  "s3:GetBucketLocation",
                  "s3:GetObject",
                  "s3:ListBucket",
                  "s3:ListBucketMultipartUploads",
                  "s3:PutObject"
                ],
                resources: [
                  s3Bucket.bucketArn,
                  s3Bucket.bucketArn + "/*"
                ]
              }), 
              new iam.PolicyStatement({   // for AWS glue data catalog
                  effect: iam.Effect.ALLOW,
                  actions: [
                    "lambda:InvokeFunction", 
                    "lambda:GetFunctionConfiguration" 
                  ],
                  resources: [lambdafirehose.functionArn],
                }),
              new iam.PolicyStatement({   // for AWS glue data catalog (data format conversion)
                effect: iam.Effect.ALLOW,
                actions: [
                  "glue:GetTable",
                  "glue:GetTableVersion",
                  "glue:GetTableVersions"
                ],
                resources: ['*'],
              }),                
            ]
          })
        }    
    });
    firehoseRole.addManagedPolicy({
      managedPolicyArn: 'arn:aws:iam::aws:policy/AWSLambdaExecute',
    });  

    const firehose = new kinesisfirehose.CfnDeliveryStream(this, 'FirehoseDeliveryStream', {
      deliveryStreamType: 'KinesisStreamAsSource',
      kinesisStreamSourceConfiguration: {
        kinesisStreamArn: stream.streamArn,
        roleArn: firehoseRole.roleArn,
      },      
      extendedS3DestinationConfiguration: {
        bucketArn: s3Bucket.bucketArn,
        bufferingHints: {
          intervalInSeconds: 60,
          sizeInMBs: 128    // mininum 64MBs at data format conversion 
        },
        compressionFormat: 'UNCOMPRESSED', // GZIP, SNAPPY
        encryptionConfiguration: {
          noEncryptionConfig: "NoEncryption"
        },
        prefix: "businfo/",
        errorOutputPrefix: 'eror/',
        roleArn: firehoseRole.roleArn,
        processingConfiguration: {
          enabled: true,
          processors: [
              {
                  type: 'Lambda',
                  parameters: [
                      {
                          parameterName: 'LambdaArn',
                          parameterValue: lambdafirehose.functionArn
                      }
                  ]
              }
          ]
        }, 

      // To-Do: how to set file translation format 
      /*  dataFormatConversionConfiguration: {
          enabled: true,
          inputFormatConfiguration: {
            deserializer: {
              openXJsonSerDe: {
                caseInsensitive: false,
                columnToJsonKeyMappings: {},
                convertDotsInJsonKeysToUnderscores: false,
              },
            },
          },
          outputFormatConfiguration: {
            serializer: {
              parquetSerDe: {
                compression: 'UNCOMPRESSED', // GZIP, SNAPPY
              },
            },
          },
          schemaConfiguration: {
            databaseName: databaseName, // Target Glue database name
            roleArn: parquetRole.roleArn,
            tableName: '01' // Target Glue table name
          }, 
        }, */
      }
    });      

    new athena.CfnWorkGroup(this, 'analytics-athena-workgroup', {
      name: `businfo-workgroup`,
      workGroupConfiguration: {
        resultConfiguration: {
          outputLocation: `s3://${s3Bucket.bucketName}`,
        },
      },
    })
  }
}
