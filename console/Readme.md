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


## [Amazon S3에 Bucket 생성]


