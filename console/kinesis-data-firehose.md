# Kinesis Data Firehose의 Delivery Stream 설정

1) Kinesis Data Firehose에 대한 Console로 접속합니다. 

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

2) [Delivery streams]에서 [Create delivery stream]을 선택합니다.   
 
![noname](https://user-images.githubusercontent.com/52392004/163908006-62909eda-d3cd-4eff-96ef-83fcb3676554.png)


3) [Create a delivery stream]에서 아래와 같이 [Source]로 "Amazon Kinesis Data Streams"을 설정하고, [Destination]은 "Amazon S3]을 선택합니다. 그리고 Source settings에서 [Browse]를 선택하여 기 생상헌 "kinesis-businfo"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163908656-1879558b-8c57-4010-9f3f-a1582fb7520d.png)

4) 아래로 스크롤하여 [Destination settings] - [S3 bucket]에서 [Browse]를 선택하여, 기 생성한 S3 bucket을 선택합니다. 여기서는 "s3-businfo"로 생성하였으므로 아래와 같이 선택합니다. [S3 bucket prefix]에는 "businfo"로 입력하고 "S3 bucket error output prefix"에는 "error"라고 입력합니다. [Create delivery stream]을 선택합니다.

![noname](https://user-images.githubusercontent.com/52392004/163909424-ea79283d-22ad-4917-b6df-3cc54262e90b.png)

5) 아래와 같이 Delivery stream이 생성된것을 확인 할 수 있습니다. 

![noname](https://user-images.githubusercontent.com/52392004/163909557-dafa31d7-f72d-4625-ab47-2b0d6f5a1b50.png)
