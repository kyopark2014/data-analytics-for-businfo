# Parquet 포맷으로 변경

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

7) [Add a data store] - [Include path]에서 오른쪽 Directory Icon을 선택하여 S3 생성시 만든 bucket을 선택합니다. 여기서는 "s3-businfo"로 bucket을 생성하였으므로 "s3//s3-businfo"을 선택합니다. 이후 [Next]를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163973390-0c469fc5-6e3b-4e0b-831b-718f7a33e0f4.png)

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

![noname](https://user-images.githubusercontent.com/52392004/163975149-f84d2d42-e850-46bd-a1d5-020d13f43452.png)

몇분 후에 [Status]가 Ready가 됩니다.

![noname](https://user-images.githubusercontent.com/52392004/163975324-1c1ed4e4-7687-4522-9eac-958cc3806340.png)

15) 
