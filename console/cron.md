# Lambda for businfo를 주기적으로 실행

1) [Amazon EventBridge Console]에 접속합니다. 

https://ap-northeast-2.console.aws.amazon.com/events/home?region=ap-northeast-2#/

2) 아래와 같이 [Rules]를 선택후 [Create rule]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163914724-e537115b-a28a-4ef7-a3db-fcdf9cc16ba6.png)

3) [Define rule detail]에서 [Name]으로 "schedule-businfo"을 입력하고, 아래처럼 [Schedule]을 선택한 다음에 [Next]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163914995-e8646c64-8503-457f-bbe7-16957a0c4675.png)

4) [Define schedule]에서 [A schudule that runs at a regular rate, such as every 10 minutes]을 선택한 다음에 [rate expression]을 아래처럼 1minute로 설정합니다. 이후 [Next]를 선택합니다. 


![noname](https://user-images.githubusercontent.com/52392004/163915341-97f504e8-fdfb-479a-95b6-d3d468fb92ae.png)

5) [Select target]에서 [select a target]으로 "Lambda function"을 선택하고, [Functions]에서 기 생성한 "lambda-for-businfo"을 선택합니다. 이후 [Next]를 선택합니다. 

6) 이후 [Next]를 선택하면 아래처럼 Review and create가 나오는데, 확인후에 아래로 스크롤하여 [Create rule]을 선택합니다. 


![noname](https://user-images.githubusercontent.com/52392004/163915886-83b71567-c7b1-446f-8cef-52a9cc481d61.png)

7) [Lambda] - [Functions] - [labmda-for-businfo]로 가면 아래와 같이 EventBridge가 설정된것을 확인 할 수 있습니다. 

![noname](https://user-images.githubusercontent.com/52392004/163916331-31e2b17d-29f5-4f48-a94b-2ecbdd35253f.png)


8) 여기까지 진행후 [Amazon S3] - [Buckets] - [s3-businfo]리 이동해서 "businfo"로 시작하는 폴더를 따라가면 아래와 같이 Kinesis Data Firehose가 저장한 event를 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163919326-1e26173e-3cdb-45b2-b105-64643fe63ab9.png)

이 데이터 중에 하나를 Download 하여 text editor로 확인해보면 아래와 같이 json 포맷으로 되어 있음을 확인 할 수 있습니다. 

```java
{"awsRegion":"ap-northeast-2","eventID":"5f27dab6-0769-4ec9-bc35-ae2289ff63e8","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo",
"dynamodb":{"ApproximateCreationDateTime":1650341393131,"Keys":{"Timestamp":{"S":"1650341392"},"RouteId":{"S":"222000073"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341392"},"PlateNo":{"S":"경기74아3282"},"RouteId":{"S":"222000073"},"PredictTime":{"S":"7"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"906ea045-479d-494e-b723-6ece1688c3c3","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo",
"dynamodb":{"ApproximateCreationDateTime":1650341452389,"Keys":{"Timestamp":{"S":"1650341451"},"RouteId":{"S":"222000073"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341451"},"PlateNo":{"S":"경기74아3282"},"RouteId":{"S":"222000073"},"PredictTime":{"S":"7"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"4cf85f06-bb27-4856-9b70-1b5bdb3cffe9","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo",
"dynamodb":{"ApproximateCreationDateTime":1650341631810,"Keys":{"Timestamp":{"S":"1650341631"},"RouteId":{"S":"222000075"}},"NewImage":{"RemainSeatCnt":{"S":"42"},"Timestamp":{"S":"1650341631"},"PlateNo":{"S":"경기74아1380"},"RouteId":{"S":"222000075"},"PredictTime":{"S":"6"}},"SizeBytes":119},"eventSource":"aws:dynamodb"}{"awsRegion":"ap-northeast-2","eventID":"aa4894e7-1414-4d74-91bf-50180f6b4838","eventName":"INSERT","userIdentity":null,"recordFormat":"application/json","tableName":"businfo",
"dynamodb":{"ApproximateCreationDateTime":1650341691690,"Keys":{"Timestamp":{"S":"1650341691"},"RouteId":{"S":"222000074"}},"NewImage":{"RemainSeatCnt":{"S":"45"},"Timestamp":{"S":"1650341691"},"PlateNo":{"S":"경기74아3244"},"RouteId":{"S":"222000074"},"PredictTime":{"S":"11"}},"SizeBytes":120},"eventSource":"aws:dynamodb"}
```
