import { WebSocket } from 'ws';
import fs from 'fs';
import path from 'path';

const parent_dir = path.dirname("../..");
const resolve_path = path.resolve(parent_dir)
const collection_path = path.join(resolve_path, 'collection.json');

export default async function main(collection_path){
    const ws = new WebSocket('ws://localhost:8080');
    ws.on('open', () => {
        let collection = fs.readFileSync(collection_path, 'utf8');
        let collection_json = JSON.parse(collection);
        for (let i = 0; i < Object.keys(collection_json).length; i++){
            let id = Object.keys(collection_json)[i];
            let content = collection_json[id];
            ws.send(
                JSON.stringify({
                   'insert':{ _id: id, content: content }
                })
            )
        }
   });
    ws.on('message', (message) => {
        console.log('Received message:', message.toString());
    });
}

main(collection_path);