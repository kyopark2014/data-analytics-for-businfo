
# Parquet으로 포맷 변경 시작

1) [Amazon Kinesis] - [Delivery streams]로 진입하여, "CdkStack-FirehoseDeliveryStream-Y7moKLyU54iD"을 선택합니다.

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

![noname](https://user-images.githubusercontent.com/52392004/163696522-b82e3916-c01e-474f-a42c-25e70490ba44.png)

2) 아래로 스크롤하여 [Transform and convert records]에서 [Edit]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696563-e1f06714-00d7-4117-ab5b-3658d59fd698.png)

3) [Record format conversion]을 "Enable"로 설정하고, [Output format]을 "Apache Parquet"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696617-77d095c7-a655-4415-9495-ff5f070790f7.png)

4) [Schema for source records]에서 [AWS Glue region]을 "Asia Pacific(Seoul"을 선택하고, [AWS Glue Database]를 "inspector"을 선택합니다. 마지막으로 [AWS Glue table]에서 [Browse]를 선택하여, Glue Crawler로 생성한 "cdkstack_cdkbusinfo2c2cf86c_1qgef8o3uv1x7"을 선택합니다. 선택이 다 되면, [Save changes]를 선택합니다.

![noname](https://user-images.githubusercontent.com/52392004/163696694-335362b8-ac2c-4396-9240-776241468d4d.png)

