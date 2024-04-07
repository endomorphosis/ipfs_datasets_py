import { PassThrough } from 'stream'
import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'


export function createClient({ accesKey, secretKey, endpoint }){
	return new S3Client({
		region: 'US',
		credentials: {
			accessKeyId: accesKey,
			secretAccessKey: secretKey
		},
		endpoint
	})
}

export function createUploadStream({ s3, bucket, key }){
	let stream = new PassThrough()
	let upload = new Upload({
		client: s3,
		leavePartsOnError: false,
		params: {
			Bucket: bucket,
			Key: key,
			Body: stream
		}
	})

	upload.on('httpUploadProgress', progress => {
		console.log(`uploaded ${progress.loaded / 1_000_000} MBs`)
	})

	return {
		stream,
		promise: upload.done()
	}
}