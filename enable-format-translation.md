
# Parquet으로 포맷 변경 시작

1) [Amazon Kinesis] - [Delivery streams]로 진입하여, "CdkStack-LimbdaKinesisFirehose925A14CE-2NEPT7t1XACq"을 선택합니다.

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

![noname](https://user-images.githubusercontent.com/52392004/163696522-b82e3916-c01e-474f-a42c-25e70490ba44.png)

2) 아래와 같이 [Configuration]을 선택한 후에 [Transform and convert records]에서 [Edit]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/194975612-a95cb72e-a852-4f9f-9e7e-833e7f4f888a.png)

3) 아래와 같이 [Transform source records with AWS Lambda]에서 [Version or alias]을 "$LATEST"를 설정합니다.

![noname](https://user-images.githubusercontent.com/52392004/194975357-63da8340-578a-43cb-92a8-48857517cae7.png)

4) 이후 아래로 스크롤하여 [Record format conversion]을 "Enable"로 설정하고, [Output format]을 "Apache Parquet"를 선택합니다. [Schema for source records]에서 [AWS Glue region]을 "Asia Pacific(Seoul"을 선택하고, [AWS Glue Database]를 "businfo"을 선택합니다. 마지막으로 [AWS Glue table]에서 [Browse]를 선택하여, Glue Crawler로 생성한 "businfo"을 선택합니다. 선택이 다 되면, [Save changes]를 선택합니다.



![noname](https://user-images.githubusercontent.com/52392004/194974891-d8889eb8-f9a6-48df-b7d5-80cf03050f5b.png)
