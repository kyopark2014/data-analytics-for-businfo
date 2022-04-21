# Amazon Crawler을 이용한 table 생성 

## AWS Glue Crawler 실행

Crawler를 실행하여 table을 생성합니다. 

1) AWS Console로 진입 합니다. 

https://ap-northeast-2.console.aws.amazon.com/glue/home?region=ap-northeast-2#catalog:tab=crawlers

2) "translate-parquet-crawler"를 선택 후에 [Run crawler]를 실행합니다. 이후 Status가 Starting -> Stoping -> Ready가 될때까지 기다립니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696272-61c7daa9-a4d4-4849-9010-b0d15e463ea1.png)

3) [AWS Glue] - [Databases] - [Tables]를 선택하면 아래와 같이 "cdkstack_cdkbusinfo2c2cf86c_1qgef8o3uv1x7"이 생성되었음을 다시 확인합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696471-7e701a87-0768-44ea-9a59-7faa5cfd33f4.png)

4) [Amazon Kinesis] - [Delivery streams]로 진입하여, "CdkStack-FirehoseDeliveryStream-Y7moKLyU54iD"을 선택합니다.

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

![noname](https://user-images.githubusercontent.com/52392004/163696522-b82e3916-c01e-474f-a42c-25e70490ba44.png)

5) 아래로 스크롤하여 [Transform and convert records]에서 [Edit]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696563-e1f06714-00d7-4117-ab5b-3658d59fd698.png)

6) [Record format conversion]을 "Enable"로 설정하고, [Output format]을 "Apache Parquet"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696617-77d095c7-a655-4415-9495-ff5f070790f7.png)

7) [Schema for source records]에서 [AWS Glue region]을 "Asia Pacific(Seoul"을 선택하고, [AWS Glue Database]를 "inspector"을 선택합니다. 마지막으로 [AWS Glue table]에서 [Browse]를 선택하여, Glue Crawler로 생성한 "cdkstack_cdkbusinfo2c2cf86c_1qgef8o3uv1x7"을 선택합니다. 선택이 다 되면, [Save changes]를 선택합니다.

![noname](https://user-images.githubusercontent.com/52392004/163696694-335362b8-ac2c-4396-9240-776241468d4d.png)
