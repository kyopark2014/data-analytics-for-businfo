# DynamoDB에서 Table 생성

1) [DynamoDB Console]에 접속합니다. 

https://ap-northeast-2.console.aws.amazon.com/dynamodbv2/home?region=ap-northeast-2#tables

2) Table을 생성하기 위하여 [Create Table]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163905197-31e70b0e-8d34-4e94-bc93-21792293a04b.png)

3) [Create table]에서 Table name으로 "businfo"를 입력하고, Partition key로 "RouteId", Sort key로 "Timestamp"을 설정합니다. 이후 아래로 스크롤하여 [Create table]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163905484-53eba406-6476-48ad-93c5-17d1679b9c1c.png)

4) 아래와 같이 businfo라는 table이 생성됨을 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163905594-3e743d55-7600-4853-914d-7c91d7258136.png)
