K nearest neighbors over filecoin

original concept idea: https://github.com/filecoin-project/devgrants/issues/923#issuecomment-1232305919

This was meant as a method of using K nearest neighbors to do a search over files thare are located on filecoin, where the entire search process itself is distributed using filecoin. so far the KNN process can ingest text from a folder and export a KNN index to JSON, sqlite, or web3storage.

the index does not contain the file itself, instead each embedding is indexed, and each embedding points to a start token and end token in the document.

it supports several huggingface embeddings, but unfortunately for you guys, I did not include my cloud intrastructure package, so all the model weight delivery, autoscaling, and queueing stuff isn't in here.

embedding_models = [
    "text-embedding-ada-002",
    "gte-large",
    "gte-base",
    "bge-base-en-v1.5",
    "bge-large-en-v1.5",
    "instructor",
    "instructor-xl"
]

ingestion uses a sliding window method, where a sliding window 1/2 the size of the context is taken on each pass for the respective models. First text-embedding-ada-002 with 8192 tokens, which is itself split into smaller chunks of 512 using the sliding window method.

Then the large chunks of 8192 are summarized using openAI into 512 tokens, and then those summaries are themselves summarized into a supersummary,those summaries and supersummaries are also indexed. Each embedding has a set of metadata, relationships, and parsing settings, to keep track of summaries, parent nodes, child nodes, start token, end token, etc.

During the retrieval process, the first step is to use text-embedding-ada-002 to retrieve the selected number of results using K nearest neigbors, then the child embeddings are taken from those, and those children are reduced to the selected numbers if 512 token final results.

TODO: implement HSNW. (done)
TODO: implement sharding of vector stores when size exceeds 100MB

Examples:

https://bafkreih3iqd6xiadh5bgpltfd3zswa7rybvtcpnqhqh646q6yc4jsiv3fa.ipfs.w3s.link/
https://bafkreieyud5mkb77crw7m4bw5zl2sqtadgftx7gi7ydfiin6w6df4336cu.ipfs.w3s.link/
https://bafybeifm3p4wl2anf5uhgmedpjgkaz7qm2qiezo63eunvqcczg3nbm6qf4.ipfs.w3s.link/
https://bafkreifzlvsja3nuvplhpopq6hddjhduyyemd5uu762nodk6feefmfrb3q.ipfs.w3s.link/
https://bafkreigv7ptbmiruodtr5ohf2sre6bccvpz2x3jdu5mls4afcs4kmrqd6e.ipfs.w3s.link/
https://bafkreiexewnxvwhp2siwldho5gyvdsk5njeienzzokbmueqd6m2jsrhosy.ipfs.w3s.link/
