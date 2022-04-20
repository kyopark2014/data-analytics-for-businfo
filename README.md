# Amazon Serverless를 이용한 실시간 버스 정보 수집 및 저장

본 github repository는 버스 정보를 주기적으로 수집하여 분석할 수 있도록, Amazon Serverless인 Amazon Kinesis Data Stream, Kinesis Data Firehose, Lambda, DynamoDB, S3를 이용합니다. 인프라는 IaC(Infrastructure as Code) 툴인 AWS CDK를 이용해 구성합니다. 

## 문제 정의

"센터필드 정류장에서 얼마나 오래 기다려야 버스를 탈 수 있을까?" 

센터필드 정류장에는 다양한 버스들이 도착하는데, 이 버스들을 타기 위해 탑승객들이 얼마나 기다리는지 알고 싶다는 요구가 있다고 가정합니다. 버스를 기다리는 시간은 버스회사에서 알려주는 예상 도착 시간이 있으나, 출퇴근 트래픽이 극심한 센터필드 버스 정류장은 버스 도착 시간이 예상 도착시간보다 더 오래 걸리기도 합니다. 버스 도착 예상시간의 변화를 분석하면, 현재의 트래픽에 따른 버스의 지연시간을 예측할 수 있고, 전날 또는 평일/주말을 비교하면, 좀 더 정확한 예측이 가능합니다. 

여기서는 버스 도착 시간에 대한 구체적인 예측이 가능하도록, 센터필드 버스 정류장에 도착하는 버스 정보를 수집하여 저장 합니다. 이를 통해, 현재 문제에 대한 구체적인 수치를 확보하고, 향후 문제를 풀때 필요한 각종 데이터를 확보할 수 있습니다. 

## Architecture 구성 

전체적인 구현 Architecture는 아래와 같으며, 데이터를 저장하는 Data Ingention 부분과 수집된 데이터를 분석에 맞도록 가공하는 Analytics로 크게 나누어지며, 인프라 관리를 위한 AWS CDK와 로깅을 위한 Amazon CloudWatch로 구성됩니다. 여기서, Amazon Lambda가 수집한 데이터를 Amazon DynamoDB에 저장하고, 이때 발생한 event를 stream 형태로 Kinesis Data Stream이 가져가 필요한 데이터로 가공합니다. 

아래의 Data Ingestion에 해당하는 Amzaon Lambda와 Amazon DynamoDB 조합은, 필요시 다른 API를 이용해 DynamoDB에 저장된 이력들을 조회 가능하도록 구현하였으나, 이련 용도 없이 단순히 데이터 수집 용도로만 사용시에는 DynamoDB 없이 Lambda로 부터 Amazon Kinesis Stream을 통해 바로 데이터를 수집 할 수 있습니다. 

<img width="806" alt="image" src="https://user-images.githubusercontent.com/52392004/164125495-7a1c8057-b8e9-4ef0-882a-8516d3721c62.png">


주요 사용 시나리오는 아래와 같습니다.

1. EventBridge를 통해 Cron job 형태로 Lambda가 Centerfied 버스정류장에 도착하는 버스정보를 정기적으로 조회하여 DynamoDB에 저장합니다. 

2. DynomoDB에 INSERT되는 이벤트를 Kinesis Data Stream으로 전달합니다.

3. Kinesis Data Stream이 Queue형태로 저장한 데이터를 Kinesis Data Firehose가 받아서, 분석에 적합하도록 데이터를 변환 합니다.

4. 변환된 데이터를 분석이 용이하도록 AWS Glue Data Catalog를 이용해 parquet 형식으로 변환하여, S3에 저장합니다.
 
5. S3에 저장된 데이터는 Amazon Athena를 통해 읽고 분석합니다. 


## 버스 도착 정보 조회

경기버스 노선정보는 [버스정보조회](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/bus-info.md) 를 이용하여 읽어올 수 있습니다. 


## 주기적인 버스 정보 수집

[Amazon CDK로 정의한 event rule](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/cdk/lib/cdk-stack.ts)을 이용하여, 아래와 같이 정기적으로 버스 정보를 열람합니다. [Lambda for businfo](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/cdk/repositories/lambda-businfo/index.js)는 Bus open api를 호출하여 DynamoDB에 저장합니다.  

```java
    const rule = new events.Rule(this, 'Cron', {
      description: "Lambda to save arrival time of buses",
      schedule: events.Schedule.expression('rate(1 minute)'),
    }); 
    rule.addTarget(new targets.LambdaFunction(lambdaBusInfo));
```

## Amazon Kinesis Data Stream로 수집되는 정보 

Amazon Kinesis Data Stream으로 수집된 정보를 Queue처럼 Shard에 저장 합니다. 저장된 스트림 데이터는 필요한 서비스들이 호출하여 사용할 수 있는데, 여기서는 Amazon Kinesis Data Firehose 이외에도 [Lambda for Kinesis](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/lambda-kinesis.md)를 이용해 스트림 데이터의 데이터를 모니터링 하고 필요시 추가적인 데이터를 수집합니다. 

## Amazon Kinesis Data Firehose로 전달된 데이터를 Lambda로 변환

Amazon Kinesis Data Firehose에 전달된 데이터는 DynamoDB에 INSERT 이벤트 정보이므로, 버스에 대한 정보 이외에도 DynamoDB에 대한 이벤트 정보가 포함되어 있습니다. 버스에 대한 정보만을 [Lambda for Firehose](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/lambda-firehose.md)을 이용하여 추출하는 변환 작업을 합니다.

## Parquet 로 형식 변환 

연속적으로 Amazon Kinesis Data Stream으로 수집된 정보를 Amazon S3에 저장 후 활용하기 위해서, 저장하는 용량이나 성능에서 유용한 parquet로 변환하고자 합니다. 

이를위해 Amazon Glue Data Catalog 기능인 Crawler를 이용해, Table을 생성하고, Amazon Kinesis Fiehose에서 Parquet 변환을 합니다.

## Athena Work Group 설정 

AWS CDK로 아래와 같이 Athena Work Group을 설정합니다. 

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

## 인프라 생성 및 삭제 

[AWS CDK](https://github.com/kyopark2014/technical-summary/blob/main/cdk-introduction.md)를 이용하여 인프라를 생성할 수 있습니다. 상세한 내용은 [AWS CDK로 Data Ingestion](https://github.com/kyopark2014/data-inggestion-using-kinesis/blob/main/cdk/README.md)을 참고하시기 바랍니다.

인프라 생성 명령어 

```c
$ cdk synth
$ cdk deploy
```

인프라 삭제 명령어 

```c
$ cdk destroy
```

Crawler를 초기 설정하는 부분이 있어서, Console에서 일부 작업이 필요합니다. [Deploy 추가 사항](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/deploy.md)에 따라, 필요한 작업을 수행합니다.

AWS CDK 사용이 익숙하지 않은 경우에 Console에서도 인프라 생성이 가능합니다. [Console 에서 인프라 생성](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/console/Readme.md)을 참고하시기 바랍니다.

## 시험 및 결과

AWS CDK로 현재 인프라를 deploy하면, Cron Rule에 따라 Lambda가 정기적으로 버스의 실시간 정보를 조회하여 DynamoDB에 저장하고 Amazon Kinesis를 통해 Parquet 형식으로 S3에 저장됩니다. Amazon S3에 저장된 버스 정보는 아래와 같이 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163661209-f81d4bc1-8438-454a-aa2f-9ead2e09124c.png)

Athena로 조회한 Table 정보는 아래와 같습니다. 

<img width="900" alt="image" src="https://user-images.githubusercontent.com/52392004/163711108-bdbf7f3e-2a2c-4ef8-bbda-58512c4beaaa.png">

Athena 조회시 아래와 같이 S3에 csv, meta 파일을 생성됨을 확인 할 수 있습니다.

<img width="1003" alt="image" src="https://user-images.githubusercontent.com/52392004/163711189-00e5122a-d187-40f9-ade3-d20e6af704b9.png">

아래는 생성된 csv에 저장된 데이터의 예 입니다. 

<img width="818" alt="image" src="https://user-images.githubusercontent.com/52392004/163711367-be6c51a4-5300-4bc7-919a-481373dceeac.png">
