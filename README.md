# Data Inggestion using Kinesis Data Stream and Kinesis Firehose toward Amazon S3

본 github repository를 이용해 Amazon의 Kinesis Data Stream와 관련된 AWS 서비스에 대해 실제적인 사용방법을 전달하고자 합니다.

## 문제 정의

데이터를 주기적으로 가져오는 동작을 예제로 보여주기 위하여 아래와 같은 문제를 설정하였습니다. 

"센터필드 정류장에서 얼마나 오래 기다려야 버스를 탈 수 있을까?"

센터필드 정류장에는 다양한 버스들이 도착하는데, 이 버스들을 타기 위해 탑승객들이 얼마나 기다리는지 알고 싶다는 요구가 있다고 가정하고 상기 문제를 Amazon Lambda Cronjob, Amazon Kinesis Data Stream을 통해 구현하고자 합니다. 여기서는 버스를 기다리는 평균 시간을 계산하고자 하므로, 일정시간(예: 10초) 간격으로 버스를 타려는 탑승객들이 오고, 이 시점에 버스 도착 예정시간이 버스 도착시간으로 가정하였습니다. 센터필드 정류장이 있는 톄혜란로는 트래픽이 매우 심하므로, 버스 도착 예정시간과 실제 도착시간은 다를 수 있습니다. 이것은 추후 ML을 통해 추론하는 별도 프로젝트로 진행합니다. 

## Architecture 구성 

전체적인 구현 Architecture는 아래와 같습니다.

![image](https://user-images.githubusercontent.com/52392004/163492939-0f712f1d-dfa8-430a-bd13-b90ec8088ba1.png)


주요 사용 시나리오는 아래와 같습니다.

1. Cron job 형태로 Lambda가 Centerfied 버스정류장에 도착하는 버스정보를 정기적으로 조회하여 DynamoDB에 저장합니다.

2. DynomoDB에 Write되는 이벤트를 Kinesis Data Stream으로 전달합니다.

3. Kinesis Data Stream이 Queue형태로 저장한 데이터를 Kinesis Firehose가 S3에 저장합니다.

4. S3에 저장된 데이터는 Amazon QuickSight를 통해 원하는 데이터를 화면에 보여줍니다.


## 버스 도착 정보 조회

여기서는 정기적으로 데이터가 들어오는 상황을 만들기 위하여, 경기버스 노선정보를 정기적으로 조회하여 Amazon DynamoDB에 저장하고자 합니다. [버스정보조회](https://github.com/kyopark2014/kinesis-data-stream/blob/main/bus-info.md) 에서 확인한 정류장 정보를 활용하여 아래에 대한 정보를 조회하고자 합니다.  

- 센터필드 정류장: stationId=122000202
- 검색하려는 노선 경로: routeId: routeID=222000074
- 해당 노선에서 센터필드 정류장의 순번: staOrder=81
- 노선번호: 1100

아래와 같이 검색할 수 있습니다. 

http://openapi.gbis.go.kr/ws/rest/busarrivalservice?serviceKey=1234567890&stationId=122000202&routeId=222000074&staOrder=81

상기 API를 통해 "경기74아3257" 버스가 12분후에 도착예정이며, 현재 43개의 좌석이 비어 있음을 알 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/162734910-16d8b31f-3ffd-428d-85d4-ce63a818c040.png)

## 주기적인 버스 정보 수집

[Amazon CDK로 정의한 event rule](https://github.com/kyopark2014/kinesis-data-stream/blob/main/cdk/lib/cdk-stack.ts)에 의해, 아래와 같이 1분 단위로 버스 도착 정보를 열람합니다. [Lambda for businfo](https://github.com/kyopark2014/kinesis-data-stream/tree/main/cdk/repositories/get-businfo)는 Bus open api를 호출하여 DynamoDB에 저장합니다.  

```java
    const rule = new events.Rule(this, 'Cron', {
      description: "Lambda to save arrival time of buses",
      schedule: events.Schedule.expression('rate(1 minute)'),
    }); 
    rule.addTarget(new targets.LambdaFunction(lambdaBusInfo));
```
    
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


## 저장된 데이터

AWS CDK로 현재 인프라를 deploy시 아래와 같이 S3로 버스정보가 저장되는것을 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163538332-fc992270-f405-44c5-96e0-652935720c9a.png)
