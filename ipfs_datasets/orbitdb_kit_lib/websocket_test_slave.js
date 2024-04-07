import { WebSocket } from 'ws';

export default async function main(){
    const ws = new WebSocket('ws://localhost:8888');
    ws.on('open', () => {
        ws.send(JSON.stringify({'insert': { _id: '1', content: 'content 1' }}))

        ws.send(JSON.stringify({'select': { _id: '1' }}))
        
        ws.send(JSON.stringify({"update": { _id: '1', content: 'content 2' }}))
        
        ws.send(JSON.stringify({'delete': { _id: '1' }}))
    });
    ws.on('message', (message) => {
        console.log('Received message:', message.toString());
    });
}

main();