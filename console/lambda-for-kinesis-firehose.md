# Lambda for Kinesis 생성

[Lambda for Firehose](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/lambda-firehose.md)는 Kinesis Data Firehose로 들어오는 데이터를 적절한 포맷으로 변환을 합니다. 

1) Lambda Console로 이동합니다. 

https://ap-northeast-2.console.aws.amazon.com/lambda/home?region=ap-northeast-2#/functions

2) [Create function]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163928328-6425c55e-a295-48fe-b99b-4cedbf12798c.png)

3) [Create function]에서 [Function nmae]으로 "lambda-for-firehose"를 입력하고, 하단의 [Create function]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163928857-8a157658-968d-48e4-9c41-3da78a73438a.png)

4) [github](https://github.com/kyopark2014/data-analytics-for-businfo/blob/main/cdk/repositories/lambda-kinesis-firehose/index.js)에서 코드를 가져와서 등록합니다. 

전체 코드를 복사하여 index.js에 복사합니다. 복사후에는 [Deploy]를 선택하여 Lambda 코드를 반영합니다. 

![image](https://user-images.githubusercontent.com/52392004/163931657-99fdaf27-6ade-46de-be03-3f15aaf6cee3.png)


5) [configuration] - [permission]을 선택후 Role name을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163935816-3c154c80-e68e-4961-bb2c-48f7b51da23a.png)

6) [Permissions policies]에서 아래와 같이 [Policy name]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163935972-52755b23-6ba8-4863-9ecb-ba95b1d165e5.png)

7) [JSON] 선택후 아래의 Permission을 추가합니다. [Review policy]를 선택 후에 [Save changes]를 선택하여 저장합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163936533-35c54890-b40c-40c8-8020-25f7cc73eb8b.png)


```java
        {
            "Effect": "Allow",
            "Action": [
                "kinesis:DescribeStream",
                "kinesis:DescribeStreamSummary",
                "kinesis:GetRecords",
                "kinesis:GetShardIterator",
                "kinesis:ListShards",
                "kinesis:SubscribeToShard"
            ],
            "Resource": [
                "arn:aws:kinesis:ap-northeast-2:[Account Number]:stream/kinesis-businfo"
            ]
        }
```        

8) [IAM] - [Roles]의 Console로 이동합니다. 

https://us-east-1.console.aws.amazon.com/iamv2/home#/roles

9) Roles에서 "Roles"를 검색하여 "AWSGlueServiceRole-businfo"을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163978615-7effde57-5ebc-4fe4-a033-60884148ba66.png)


10) 
