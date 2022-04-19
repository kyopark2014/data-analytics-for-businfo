# Lambda for Businfo

## Lambda 생성 

1) 관련 코드를 적당한 폴더에 다운로드 합니다. 

```c
$ git clone https://github.com/kyopark2014/data-analytics-for-businfo
```
2) Lambda Console에 진입합니다.

https://ap-northeast-2.console.aws.amazon.com/lambda/home?region=ap-northeast-2#/functions

3) [Create function]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163894572-cbe89c3f-b272-4316-8588-9fc8aa6160bd.png)

4) [Funtion name]에 "lambda-for-businfo"라고 입력후 [Create function]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163894772-09ea9d70-cdfe-405a-ae5c-2c2115d9a34e.png)

5) [Lambda] - [Functions] - [lambda-for-businfo]에서 아래와 같이 [Upload form]을 선택한후 sub menu에서 ".zip file"을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163895338-784295ab-ce05-4266-aea1-2b82b48c85f5.png)

6) [Uplaod]를 선택하여 "data-analytics-for-businfo/tree/main/cdk/repositories/lambda-businfo"에 있는 "deploy.zip"을 선택합니다. 

![image](https://user-images.githubusercontent.com/52392004/163895413-03f9e205-8ebb-4599-a3b9-0ba6fe97ad98.png)

7) 아래처럼 코드가 로드 되었는지 확인 합니다. 

![image](https://user-images.githubusercontent.com/52392004/163895641-de324c44-4b79-4960-995a-76ed792902e5.png)

8) 아래와 같이 [Configuration] - [Environment variables]에서, "Edit"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163895816-aff4341f-32a9-4b10-ac9d-91f22a1ee92c.png)

9) [Edit environment varialbles]에서 [Add environment variable]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163895907-b984f8e2-0ba2-4776-bb2d-974c5513d690.png)

10) Lambda for businfo가 버스 Open API를 통해 얻어온 정보를 DyanmoDB에 저장하기 위해, Lambda for businfo에 DynamoDB의 Table Nam을 알려주고자 합니다. [Key]에 "tableName"을 입력하고, [Value]에 "businfo"라고 입력한다음 [Save] 합니다. 
 
![noname](https://user-images.githubusercontent.com/52392004/163904803-c5a9dede-3fc4-4b60-803b-e6eec7b4e385.png)

