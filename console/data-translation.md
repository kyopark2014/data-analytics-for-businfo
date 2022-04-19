# Data Translation을 위한 Kinesis Data Hose 설정

1) Kinesis Data Firehose Console로 접속합니다. 

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

2) [Delivery streams]에서 기 생성한 Kinesis Data Firehose를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163968856-a848f713-9562-4d08-b280-5f3840121cd0.png)

3) 아래와 같이 [Configuration]을 선택 후에, [Transform and convert records]에서 [Edit]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163969344-f4ed537e-7245-43e2-8121-f76d59973dd2.png)

4) [Edit transform and covert records]에서 [Data transformation]을 "Enabled"로 설정합니다. 그리고 [AWS Lambda function]에서 [Browse]를 선택하여 "lambda-for-firehose"을 선택합니다. 이후 아래로 스크롤하여 [Save changes]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163969991-9a8933db-a5bc-4ce1-a93c-44c1008922c9.png)

5) 설정 후에 다시 Amazon S3의 "s3-businfo" bucket에서 최신으로 저장된 결과를 다운로드하여 보면 아래와 같이 json 파일의 내용이 변경된것을 확인 할 수 있습니다. 

```java
{"timestamp":"1650355371","routeId":"222000073","remainSeatCnt":"44","plateNo":"경기74아3273","predictTime":"11"}{"timestamp":"1650355371","routeId":"222000075","remainSeatCnt":"39","plateNo":"경기74아1370","predictTime":"1"}{"timestamp":"1650355431","routeId":"222000076","remainSeatCnt":"45","plateNo":"경기74아3798","predictTime":"9"}{"timestamp":"1650355491","routeId":"222000075","remainSeatCnt":"39","plateNo":"경기74아1370","predictTime":"1"}{"timestamp":"1650355551","routeId":"222000073","remainSeatCnt":"44","plateNo":"경기74아3273","predictTime":"15"}{"timestamp":"1650355551","routeId":"222000074","remainSeatCnt":"45","plateNo":"경기74아3249","predictTime":"20"}
```
