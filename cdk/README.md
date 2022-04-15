# AWS CDK로 Data Ingestion  

Amazon S3를 아래와 같이 정의 합니다. bucket name과 arn은 아래와 같이 확인 가능 합니다. 

```java
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
```

Amazon Kinesis Data Stream을 아래와 같이 선언합니다. 또한 matic도 모니터링을 위해 추가 합니다. 

```java
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
```

Amazon Kinesis Firehose를 선언하기 전에 Role을 설정하여야 합니다. Amazon S3에 저장하기 위한 Permission과 Amazon Kinesis Data Stream에 접근하기 위한 Permission을 정의하여야 합니다. 

```java
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
            ]
          })
        }    
    });
```

Amazon Kinesis Datahose를 아래와 같이 선언합니다. S3에 저장할때의 configuration과 압축 설정, S3에 저장할때 사용할 prefix등을 정의합니다. 
```java
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
    });  
```

Amazon DynamoDB를 정의하고, 변경내역을 stream으로 Kinesis에 전달하도록 합니다. 
```java
    const tableName = 'dynamodb-businfo';
    const dataTable = new dynamodb.Table(this, 'dynamodb-businfo', {
        tableName: tableName,
        partitionKey: { name: 'RouteId', type: dynamodb.AttributeType.STRING },
        sortKey: { name: 'Timestamp', type: dynamodb.AttributeType.STRING },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        kinesisStream: stream,
    });
```


버스 정보를 조회하는 Amazon Lambda를 정의합니다. 
```java
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
```

Lambda에서 주기적으로 버스정보를 읽어 올 수 있도록, 아래와 같이 Cron Rule을 정의 합니다. 
```java
    const rule = new events.Rule(this, 'Cron', {
      description: "Schedule a Lambda to save arrival time of buses",
      schedule: events.Schedule.expression('rate(1 minute)'),
    }); 
    rule.addTarget(new targets.LambdaFunction(lambdaBusInfo));
```

때로는 Amazon Kinesis에서 stream을 직접 확인하고 싶을수 있습니다. 이를 위해 event로 stream을 로그로 찍는 Lambda를 하나 만들었고, 아래와 같이 Amazon CDK로 선언하여 사용할 수 있습니다. 

```java
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
```    
