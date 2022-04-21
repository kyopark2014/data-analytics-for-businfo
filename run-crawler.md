# Amazon Crawler을 이용한 변환 table 생성 

## AWS Glue Crawler 실행

Crawler를 실행하여 table을 생성합니다. 

1) AWS Console로 진입 합니다. 

https://ap-northeast-2.console.aws.amazon.com/glue/home?region=ap-northeast-2#catalog:tab=crawlers

2) "translate-parquet-crawler"를 선택 후에 [Run crawler]를 실행합니다. 이후 Status가 Starting -> Stoping -> Ready가 될때까지 기다립니다. 

![noname](https://user-images.githubusercontent.com/52392004/163696272-61c7daa9-a4d4-4849-9010-b0d15e463ea1.png)

3) [AWS Glue] - [Databases] - [Tables]를 선택하여, 아래와 같이 "businfo"로 Table이 생성되었음을 확인합니다. 

![noname](https://user-images.githubusercontent.com/52392004/164422093-528f3e1a-5483-4800-b982-6786bc8b94c5.png)


