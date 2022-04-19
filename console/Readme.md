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

### [Lambda for firehose 구현](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/lambda-for-kinesis-firehose.md) 

Lambda for firehose는 Kinesis Data Firehose에 들어오는 데이터를 원하는 포맷으로 변환 합니다. 

### [Data Translation 위한 Kinesis Data Firehose 설정](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/data-translation.md)

Lambda for firehose를 이용해 Data Translation을 할 수 있도록 설정 합니다. 

설정 후에 다시 Amazon S3의 "s3-businfo" bucket에서 최신으로 저장된 결과를 다운로드하여 보면 아래와 같이 json 파일의 내용이 변경된것을 확인 할 수 있습니다. 

```java
{"timestamp":"1650355371","routeId":"222000073","remainSeatCnt":"44","plateNo":"경기74아3273","predictTime":"11"}{"timestamp":"1650355371","routeId":"222000075","remainSeatCnt":"39","plateNo":"경기74아1370","predictTime":"1"}{"timestamp":"1650355431","routeId":"222000076","remainSeatCnt":"45","plateNo":"경기74아3798","predictTime":"9"}{"timestamp":"1650355491","routeId":"222000075","remainSeatCnt":"39","plateNo":"경기74아1370","predictTime":"1"}{"timestamp":"1650355551","routeId":"222000073","remainSeatCnt":"44","plateNo":"경기74아3273","predictTime":"15"}{"timestamp":"1650355551","routeId":"222000074","remainSeatCnt":"45","plateNo":"경기74아3249","predictTime":"20"}
```

### [AWS Glue Data Catalog 설정](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/format-parquet.md)

AWS Glue Data Catalog를 이용하여 json 파일을 Amazon Athena등에서 사용하기 용이하도록 parquet 형식으로 변환합니다. 

### [Amazon Athena를 이용한 분석](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/athena.md)

AWS Athena에서 workgroup을 설정하고 query를 시험합니다. 
