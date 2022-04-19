# Data Analytics for Businfo를 Console로 작성하는 방법

여기서는 AWS CDK가 아닌 Console로 인프라를 구성하는 방법에 대해 소개 합니다.

## [Lambda for Businfo](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/lambda-for-businfo.md)

Lambda for Businfo는 센터필드 버스정류장에 도착하는 버스의 정보를 경기버스를 통해 제공되는 open api로 조회하고 DynamoDB로 저장을 수행합니다. 


## [DynamoDB에 Table 생성](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/dynamodb.md)

Bus 도착정보를 위한 DynamoDB Table을 생성합니다. 


## [Kinesis Data Stream 생성](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/kinesis-data-stream.md)

DynamoDB event를 stream 형태로 수신받기 위하여 Kinesis Data Stream을 생성합니다. 

## [Event Stream으로 연결](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/kinesis-event-source.md)

Kinesis Data Stream이 DynamoDB의 Event를 수신할 수 있도록 설정합니다. 

## [Amazon S3에 Bucket 생성](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/s3-bucket.md)

수집된 데이터를 저장할 수 있도록 Amazon S3에 Bucket을 생성합니다.

## [Kinesis Data Firehose 설정](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/kinesis-data-firehose.md)

Kinesis Data Stream으로 부터 stream 데이터를 받을 수 있도록 Delivery stream을 설정합니다. 

## [EventBridge 설정](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/cron.md)

Cron job을 실행하기 위하여 Amazon EventBrdide에서 Rule을 등록합니다. 

## 중간 결과 

여기까지 진행후 [Amazon S3] - [Buckets] - [s3-businfo]리 이동해서 "businfo"로 시작하는 폴더를 따라가면 아래와 같이 Kinesis Data Firehose가 저장한 event를 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163919326-1e26173e-3cdb-45b2-b105-64643fe63ab9.png)

이 데이터 중에 하나를 Download 하여 text editor로 확인해보면 아래와 같이 json 포맷으로 되어 있음을 확인 할 수 있습니다. 

```java
{"awsRegion":"ap-northeast-2","eventID":"5f27dab6-0769-4ec9-bc35-ae2289ff63e8","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo","dynamodb":{"ApproximateCreationDateTime":1650341393131,"Keys":{"Timestamp":{"S":"1650341392"},"RouteId":{"S":"222000073"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341392"},"PlateNo":{"S":"경기74아3282"},"RouteId":{"S":"222000073"},"PredictTime":{"S":"7"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"906ea045-479d-494e-b723-6ece1688c3c3","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo","dynamodb":{"ApproximateCreationDateTime":1650341452389,"Keys":{"Timestamp":{"S":"1650341451"},"RouteId":{"S":"222000073"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341451"},"PlateNo":{"S":"경기74아3282"},"RouteId":{"S":"222000073"},"PredictTime":{"S":"7"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"4cf85f06-bb27-4856-9b70-1b5bdb3cffe9","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo","dynamodb":{"ApproximateCreationDateTime":1650341631810,"Keys":{"Timestamp":{"S":"1650341631"},"RouteId":{"S":"222000075"}},"NewImage":{"RemainSeatCnt":{"S":"42"},"Timestamp":{"S":"1650341631"},"PlateNo":{"S":"경기74아1380"},"RouteId":{"S":"222000075"},"PredictTime":{"S":"6"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"aa4894e7-1414-4d74-91bf-50180f6b4838","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo","dynamodb":{"ApproximateCreationDateTime":1650341691690,"Keys":{"Timestamp":{"S":"1650341691"},"RouteId":{"S":"222000074"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341691"},"PlateNo":{"S":"경기74아3244"},"RouteId":{"S":"222000074"},"PredictTime":{"S":"11"}},"SizeBytes":120},"eventSource":"aws:dynamodb"}
```

### Lambda for firehose로 필요한 데이터만 추출 


