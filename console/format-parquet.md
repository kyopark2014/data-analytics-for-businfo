# Parquet 포맷으로 변경을 위한 Glue Data Catalog 

1) [AWS Glue]의 Database Console로 이동합니다. 

https://ap-northeast-2.console.aws.amazon.com/glue/home?region=ap-northeast-2#catalog:tab=databases

2) [Add database]를 선택합니다. 
 
![noname](https://user-images.githubusercontent.com/52392004/163971394-fd9f1c43-38f5-4532-aa89-e107ff72a99a.png)

3) [Add database] - [Database name]에 "inspector"로 입력 후에 [Create]를 선택합니다.  

![noname](https://user-images.githubusercontent.com/52392004/163971602-6b241c74-340f-4b70-a9f5-9d8de9b44da9.png)

아래와 같이 "inspector"라는 database가 생성되었음을 확인 할 수 있습니다.

![image](https://user-images.githubusercontent.com/52392004/163971864-d04fdd0e-601b-41cb-8777-d4a1f30d52c6.png)

4) 아래와 같이 [AWS Glue] - [Crawler]를 선택하고, 다시 [Add crawler]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163972220-68cd20f2-1937-4a7f-aa30-8e521720e8df.png)

5) [Crwaler name]으로 "allow-s3-glue-parquet"로 입력하고 [Next]를 선택합니다. 
 
![image](https://user-images.githubusercontent.com/52392004/163972492-df51b720-f976-4862-a703-1ea6dfb5c8dc.png)

6) 아래와 같이 변경없이 [Next]를 누릅니다.

![noname](https://user-images.githubusercontent.com/52392004/163972770-c2e25551-ed48-4026-a5c3-582ca2ea234b.png)

7) [Add a data store] - [Include path]에서 오른쪽 Directory Icon을 선택하여 S3 생성시 만든 bucket을 선택합니다. 여기서는 "s3-businfo"로 bucket을 생성하였으므로 "s3//s3-businfo/businfo2022"을 선택합니다. 이후 [Next]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163997525-019ac029-6f7a-4a21-9c8e-57f1b74c0dc5.png)


8) 아래와 같이 [Next]를 선택합니다.

![noname](https://user-images.githubusercontent.com/52392004/163973538-3e56b31d-21fe-4ccd-b050-25571f9f2a99.png)

9) [IAM role]에 "businfo"로 입력후에 [Next]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163973815-9a2b21a2-670d-478d-b676-5de64a4a5986.png)

10 아래와 같이 [Next]를 누릅니다. 

![noname](https://user-images.githubusercontent.com/52392004/163973985-54fbc4db-caba-49a8-a12e-8a9f1ff03639.png)

11) [Configure the crawler's output]에서 [Database]로 기 생성한 "inspector"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163974350-32f263ab-52be-40de-aedb-1bb428adf8cf.png)


12) [Finish]를 눌러서 설정을 저장합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163974498-ad4d1fba-434e-4e0c-9db2-bf4e58520426.png)

13) 아래와 같이 "allow-s3-glue-parquet"를 선택 후에 [Run crawler]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163974880-843a1a98-bd68-4bfd-ac25-f60feb2b8349.png)

14) [Status]가 Starting -> Stopping -> Ready가 될때까지 기다립니다. 

![noname](https://user-images.githubusercontent.com/52392004/163975324-1c1ed4e4-7687-4522-9eac-958cc3806340.png)

15) [AWS Glue] - [Tables]를 선택한 후에 아래와 같이 "s3-businfo"를 선택합니다. 아래와 같이 "timestamp", "routeId"등으로 구성된 Table이 생성되었음을 알 수 있습니다. 

![noname](https://user-images.githubusercontent.com/52392004/163982331-f30a3007-7816-4376-a971-a038d1291b55.png)

16) Kinesis Data Firehose의 "Delivery streams"에서 기 생성된 stream으로 다시 진입합니다. 

Console의 URL은 아래와 같습니다. 

https://ap-northeast-2.console.aws.amazon.com/firehose/home?region=ap-northeast-2#/streams

아래와 같이 stream을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163983272-c8a3581c-8b8b-4ab1-95ee-8e4e60165048.png)

17) stream에서 [Configuration]을 선택후 아래처럼 [Edit]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163983564-c191fa10-d6f0-4014-a328-51168e94d236.png)

18) 아래와 같이 [Record format conversion]을 "Enabled]를 설명하면 추가 메뉴가 보입니다. 여기에서 [Output format]은 "Apache Parquet"를 선택하고, [AWS Glue region]은 "Asis Pacific (Seoul)"을 선택합니다. [AWS Glue database]에는 "inspector"를 설정하고, [AWS Glue table]에서 [Browse]를 선택하여, "businfo2022"를 선택하고 마지막 하단의 [Save changes]를 선택합니다. Buffer size 설정이 필요할 경우는 "128"로 설정합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163998341-6e60ac1e-75cb-47dd-a34e-69d15d4ba341.png)


19) 여기까지 설정후 Amazon S3에 가면, 아래와 같이 최신 파일들이 parquet로 변환되고 있음을 알 수 있습니다. 

![noname](https://user-images.githubusercontent.com/52392004/163987360-93b9bbcc-e1f9-43e7-81e7-1ab934cc71ea.png)

20) json 파일과 parquet 파일이 혼재되어 있으므로, 아래와 같이 기존 파일들을 모두 삭제 합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163987758-83adcd72-e648-40ba-b5b4-3d91bb1b2bfd.png)

아래와 같이 "permanently delete" 입력하여 해당 S3 bucket을 비워줍니다. 

![noname](https://user-images.githubusercontent.com/52392004/163987951-258e1d45-53ab-40bd-90a8-ec611211045b.png)

새로 파일들이 생성되는데 시간이 걸리므로 일정시간 기다린후 다시 S3에 진입하여 parquet로 된 파일들만 생성되어 있는지 확인 합니다. 
