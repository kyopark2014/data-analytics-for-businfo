exports.handler = async (event) => {
    console.log('event: '+JSON.stringify((event)));
    
    let records = event['records'];
    let outRecords = [];
    records.forEach((record) => {
        let recordId = record['recordId'];
        let data = Buffer.from(record['data'], 'base64');
 
        let body = JSON.parse(data);
        let newimage = body['dynamodb']['NewImage'];

        let timestamp = newimage['Timestamp']['S'];
        let routeId = newimage['RouteId']['S'];
        let remainSeatCnt = newimage['RemainSeatCnt']['S'];
        let plateNo = newimage['PlateNo']['S'];
        let predictTime = newimage['PredictTime']['S'];
        
        const converted = {
            timestamp: timestamp,
            routeId: routeId,
            remainSeatCnt: remainSeatCnt,
            plateNo: plateNo,
            predictTime: predictTime
        };
        console.log('event: %j',converted);

        let binary = Buffer.from(JSON.stringify(converted), 'utf8').toString('base64');
        console.log('binary: '+binary);

        const outRecord = {
            recordId: recordId,
            result: 'Ok',
            data: binary
        }
        outRecords.push(outRecord); 
    });
    console.log('body: %j', {'records': outRecords});
    
    return {'records': outRecords}
};
