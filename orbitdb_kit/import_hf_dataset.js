import { WebSocketServer } from 'ws';

export default async function main(){
	const wss = new WebSocketServer({ port: 8888 });
	wss.on('connection', ws => {
		ws.on('message', (message) => {

			let parsed_message = JSON.parse(message);

			if(parsed_message.job == 'check_dataset'){
				check_dataset(ws, message);
			}

			if(parsed_message.job == 'upload_document'){
				upload_document(ws, message);
			}

			if(parsed_message.job == 'upload_key_value'){
				upload_key_value(ws, message);
			}

			if(parsed_message.job == 'upload_time_series'){
				upload_time_series(ws, message);
			}

			if(parsed_message.job == 'upload_indexed_key_value'){
				upload_indexed(ws, message);
			}
		});
	});
}


async function check_dataset(ws, message){
	console.log("checking dataset");
	// Check if the received dataset exists
	// if exists
		// Check the schema of the existing dataset
		// Check schema against the huggingface dataset
		// If schema matches, return dataset_exists
		// If schema does not match, return schema_mismatch
	// if not exists
		// return dataset_not_found
		
	ws.send("dataset_not_found")
}

async function upload_document(ws, message){
	console.log("uploading document");
	console.log(JSON.parse(message));
	ws.send('document_uploaded');
}

async function upload_key_value(ws, message){
	console.log("uploading key value");
	console.log(JSON.parse(message));
	ws.send('key_value_uploaded');
}

async function upload_time_series(ws, message){
	console.log("uploading time series");
	console.log(JSON.parse(message));
	ws.send('time_series_uploaded');
}

async function upload_indexed(ws, message){
	console.log("uploading indexed");

	let parsed_message = JSON.parse(message);
	console.log(parsed_message);

	
	ws.send('indexed_uploaded');
}

main();