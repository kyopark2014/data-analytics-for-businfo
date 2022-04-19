# Amazon Athena 설정

1) Amazon Athena Console의 Workgroup으로 진입합니다. 

https://ap-northeast-2.console.aws.amazon.com/athena/home?region=ap-northeast-2#/workgroups

2) 아래처럼 [Create workgroup]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163990996-8919a58a-a03e-4811-ba18-21311fdb4496.png)

3) [Create workgroup] - [Workgroup details]에서 [Workgroup name]에 "businfo-workgroup"을 입력합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163991197-b6405824-a213-4896-bef8-13d33b89a9ac.png)

4) 아래로 스크롤하여 [Query result configuration]에서 [Browse S3]를 선택힙니다. 이후 아래로 스크롤하여 [Create workgroup]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163991454-e84371b9-a2ea-4a5a-949c-8eef47912584.png)

5) table 이름으로 query시 아래처럼 bus 정보를 조회할 수 있습니다. 

![noname](https://user-images.githubusercontent.com/52392004/163996509-7e0e017c-e58e-4148-9d28-eadfd82c15d6.png)
