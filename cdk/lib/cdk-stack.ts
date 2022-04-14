import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';

import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as kinesis from 'aws-cdk-lib/aws-kinesis';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';

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

    // kinesis data stream
    const stream = new kinesis.Stream(this, 'Stream', {
      streamName: 'businfo',
      retentionPeriod: cdk.Duration.hours(48),
      streamMode: kinesis.StreamMode.ON_DEMAND
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
