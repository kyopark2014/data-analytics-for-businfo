# Amazon Serverless를 이용한 실시간 버스 정보 수집 및 저장

본 github repository은 버스 정보를 주기적으로 수집하여 분석할 수 있도록, Amazon Serverless인 Amazon Kinesis Data Stream, Kinesis Data Firehose, Lambda, DynamoDB, S3를 이용합니다. 인프라는 IaC(Infrastructure as Code) 툴인 AWS CDK를 이용해 구성합니다. 

## 문제 정의

"센터필드 정류장에서 얼마나 오래 기다려야 버스를 탈 수 있을까?" 

센터필드 정류장에는 다양한 버스들이 도착하는데, 이 버스들을 타기 위해 탑승객들이 얼마나 기다리는지 알고 싶다는 요구가 있다고 가정하고 상기 문제를 Amazon Lambda Cronjob, Amazon Kinesis Data Stream을 통해 구현하고자 합니다. 여기서는 버스를 기다리는 평균 시간을 계산하고자 하므로, 일정시간(예: 10초) 간격으로 버스를 타려는 탑승객들이 오고, 이 시점에 버스 도착 예정시간이 버스 도착시간으로 가정하였습니다. 센터필드 정류장이 있는 톄혜란로는 트래픽이 매우 심하므로, 버스 도착 예정시간과 실제 도착시간은 다를 수 있습니다. 이것은 추후 ML을 통해 추론하는 별도 프로젝트로 진행합니다. 

## Architecture 구성 

전체적인 구현 Architecture는 아래와 같습니다.

![image](https://user-images.githubusercontent.com/52392004/163705113-4d9fe08c-c912-49ed-8aba-11f7b1223374.png)


주요 사용 시나리오는 아래와 같습니다.

1. Cron job 형태로 Lambda가 Centerfied 버스정류장에 도착하는 버스정보를 정기적으로 조회하여 DynamoDB에 저장합니다.

2. DynomoDB에 Write되는 이벤트를 Kinesis Data Stream으로 전달합니다.

3. Kinesis Data Stream이 Queue형태로 저장한 데이터를 Kinesis Firehose가 S3에 저장합니다.

4. S3에 저장된 데이터는 Amazon QuickSight를 통해 원하는 데이터를 화면에 보여줍니다.


## 버스 도착 정보 조회

경기버스 노선정보는 [버스정보조회](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/bus-info.md) 를 이용하여 읽어올 수 있습니다. 


## 주기적인 버스 정보 수집

[Amazon CDK로 정의한 event rule](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/cdk/lib/cdk-stack.ts)에 의해, 아래와 같이 1분 단위로 버스 도착 정보를 열람합니다. [Lambda for businfo](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/cdk/repositories/lambda-businfo/index.js)는 Bus open api를 호출하여 DynamoDB에 저장합니다.  

```java
    const rule = new events.Rule(this, 'Cron', {
      description: "Lambda to save arrival time of buses",
      schedule: events.Schedule.expression('rate(1 minute)'),
    }); 
    rule.addTarget(new targets.LambdaFunction(lambdaBusInfo));
```

## Amazon Kinesis Data Stream에서 수집되는 정보 

[Lambda for Kinesis](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/lambda-kinesis.md)는 Amazon Kinesis Data Stream으로 수집된 정보를 확인하고자 합니다. 이것은 Amazon Kinesis Firehose에 전달되는 데이터와 동일하므로, 입력의 형태를 이해하는데 도움이 됩니다. 

## Amazon Kinesis Data Firehose에 전달된 데이터의 변환

DynamoDB에 INSERT된 이벤트에는 실제 버스에 대한 정보이외에 데이터가 았으므로, 버스에 대한 정보만을 [Lambda for Firehose](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/lambda-firehose.md)을 이용하여 변환합니다.



## 인프라 생성 및 삭제 

AWS CDK를 이용하여 인프라를 생성할 수 있습니다. 상세한 내용은 [AWS CDK로 Data Ingestion](https://github.com/kyopark2014/data-inggestion-using-kinesis/blob/main/cdk/README.md)을 참고하시기 바랍니다.

인프라 생성 명령어 

```c
$ cdk synth
$ cdk deploy
```

인프라 삭제 명령어 

```c
$ cdk destroy
```

CDK Crawler를 초기 설정하는 부분이 있어서, Console에서 작업이 필요합니다. [Deploy 추가 사항](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/deploy.md)을 선택하여, 필요한 작업을 수행합니다.

## 저장된 데이터

AWS CDK로 현재 인프라를 deploy시 아래와 같이 S3로 버스정보가 parquet 형식으로 저장되는것을 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163661209-f81d4bc1-8438-454a-aa2f-9ead2e09124c.png)
