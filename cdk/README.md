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

parquet형식으로 변환을 위해서는 crawler로 table을 생성하여야 합니다. 아래와 같이 crawler를 위한 permission을 설정합니다. 

```java
    const crawlerRole = new iam.Role(this, "crawlerRole", {
      assumedBy: new iam.AnyPrincipal(),
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
            ]
          })
      },
      managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSGlueServiceRole"),
      ],
    });
    new cdk.CfnOutput(this, 'crawlerRoleArn', {
      value: crawlerRole.roleArn,
      description: 'The arn of crawlerRole',
    });
```

아래와 같이 crawler를 설정합니다. 

```java
    const glueDatabaseName = "inspector";
    const crawler = new glue.CfnCrawler(this, "TranslateToParquetGlueCrawler", {
      name: "translate-parquet-crawler",
      role: crawlerRole.roleArn,
      targets: {
          s3Targets: [
              {path: 's3://'+s3Bucket.bucketName+'/businfo'}, 
          ]
      },
      databaseName: glueDatabaseName,
      schemaChangePolicy: {
          deleteBehavior: 'DELETE_FROM_DATABASE'
      },      
    });
```    

포맷 변경을 위한 permission을 정의 합니다. 

```java
    const translationRole = new iam.Role(this, 'TranslationRole', {
      assumedBy: new iam.AnyPrincipal(),
      description: 'TraslationRole',
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
              new iam.PolicyStatement({   
                effect: iam.Effect.ALLOW,
                actions: [
                  "lambda:InvokeFunction", 
                  "lambda:GetFunctionConfiguration", 
                ],
                resources: [
                  lambdafirehose.functionArn, 
                  lambdafirehose.functionArn+':*'],
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
            ]
          })
        },
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSGlueServiceRole"),
        ], 
    });
    translationRole.addManagedPolicy({
      managedPolicyArn: 'arn:aws:iam::aws:policy/AWSLambdaExecute',
    });  
```


Amazon Kinesis Datahose를 아래와 같이 선언합니다. S3에 저장할때의 configuration과 압축 설정, S3에 저장할때 사용할 prefix등을 정의합니다. 

```java
    const firehose = new kinesisfirehose.CfnDeliveryStream(this, 'FirehoseDeliveryStream', {
      deliveryStreamType: 'KinesisStreamAsSource',
      kinesisStreamSourceConfiguration: {
        kinesisStreamArn: stream.streamArn,
        roleArn: translationRole.roleArn,
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
        roleArn: translationRole.roleArn,
        processingConfiguration: {
          enabled: true,
          processors: [{
            type: 'Lambda',
              parameters: [{
              parameterName: 'LambdaArn',
              parameterValue: lambdafirehose.functionArn
            }]
          }]
        }, 
        // to set file translation format 
        dataFormatConversionConfiguration: {          
          enabled: false,
        }, 
      }
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

때로는 Amazon Kinesis에서 stream을 직접 확인하고 싶을수 있습니다. 이를 위해, Amazon Kinesis Stream의 fan out을 이용하는데, [Lambda for Kinesis](https://github.com/kyopark2014/kinesis-data-stream/blob/main/lambda-kinesis.md)은 stream을 event로 받아서 parsing하여, 확인할 수 있도록 log로 저장합니다.

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

Amazon Athena를 위한 workgroup을 아래와 같이 선언합니다. 

```java
    new athena.CfnWorkGroup(this, 'analytics-athena-workgroup', {
      name: `businfo-workgroup`,
      workGroupConfiguration: {
        resultConfiguration: {
          outputLocation: `s3://${s3Bucket.bucketName}`,
        },
      },
    })
```    
