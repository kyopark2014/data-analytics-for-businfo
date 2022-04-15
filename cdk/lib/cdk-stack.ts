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

    // kinesis firehose
    const firehoseRole = new iam.Role(this, 'FirehoseRole', {
      assumedBy: new iam.ServicePrincipal('firehose.amazonaws.com'),
      inlinePolicies: {
        'allow-s3-kinesis-logs': new iam.PolicyDocument({
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
                  "s3:GetObject*",
                  "s3:GetBucket*",
                  "s3:List*",
                  "s3:DeleteObject*",
                  "s3:PutObject*",
                  "s3:Abort*"
                ],
                resources: [
                  s3Bucket.bucketArn,
                      s3Bucket.bucketArn + "/*"
                    ]
                }),
            /*  new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                  "logs:PutLogEvents"
                ],
                resources: [
                  logGroup.logGroupArn
                ]
              }) */
            ]
          })
        }    
    });

    const firehose = new kinesisfirehose.CfnDeliveryStream(this, 'FirehoseDeliveryStream', {
      deliveryStreamType: 'KinesisStreamAsSource',
      kinesisStreamSourceConfiguration: {
        kinesisStreamArn: stream.streamArn,
        roleArn: firehoseRole.roleArn,
      },
      s3DestinationConfiguration: {
        bucketArn: s3Bucket.bucketArn,
        bufferingHints: {
          intervalInSeconds: 60,
          sizeInMBs: 5
        },
        compressionFormat: 'UNCOMPRESSED', // GZIP
        encryptionConfiguration: {
          noEncryptionConfig: "NoEncryption"
        },
        prefix: "businfo/",
        errorOutputPrefix: 'eror/',
        roleArn: firehoseRole.roleArn
      }, 
      //destinations: [new destinations.S3Bucket(bucket)], */
    /*  extendedS3DestinationConfiguration: {
        bucketArn: s3Bucket.bucketArn,
        bufferingHints: {
            intervalInSeconds: 60,
            sizeInMBs: 128
        },
        compressionFormat: 'UNCOMPRESSED',
        roleArn: firehoseRole.roleArn,
        prefix: 'firehose/',
        roleArn: '{ "Fn::GetAtt" : ["S3deliveryRole", "Arn"] }', 
        processingConfiguration: {
            enabled: true,
            processors: [
                {
                    type: 'Lambda',
                    parameters: [
                        {
                            parameterName: 'LambdaArn',
                            parameterValue: props.lambda.functionArn
                        }
                    ]
                }
            ]
        } 
      }*/
    });  

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
  /*  dataTable.addGlobalSecondaryIndex({ // GSI
      indexName: 'ContentID-index',
      partitionKey: { name: 'ContentID', type: dynamodb.AttributeType.STRING },
    }); */


    // Lambda - kinesisInfo
    const lambdakinesis = new lambda.Function(this, "KinesisInfo", {
      runtime: lambda.Runtime.NODEJS_14_X, 
      code: lambda.Code.fromAsset("repositories/get-kinesisinfo"), 
      handler: "index.handler", 
      timeout: cdk.Duration.seconds(3),
      environment: {
      }
    }); 

    const eventSource = new lambdaEventSources.KinesisEventSource(stream, {
      startingPosition: lambda.StartingPosition.TRIM_HORIZON,
    });
    lambdakinesis.addEventSource(eventSource);    

    // Lambda - UpdateBusInfo
    const lambdaBusInfo = new lambda.Function(this, "LambdaBusInfo", {
      runtime: lambda.Runtime.NODEJS_14_X, 
      code: lambda.Code.fromAsset("repositories/get-businfo"), 
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
  }
}
