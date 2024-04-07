import m, { render } from 'mithril'

let models = {};
let searchTerm = '';


fetch('./collection.json')
	.then(response => response.json())
	.then(data => {
		models = data
		m.redraw()
	})
	

const Main = () => {

	function byteToGigaByte(n) {
		gb = n / Math.pow(10,9);
		round = gb.toFixed(1);
		return round
	}

	function revealModelDetails(id) {
		if (document.getElementById(id).classList.contains('active')) {
			document.getElementById(id).classList.remove('active')
			return
		}else {
			document.getElementById(id).classList.add('active')
		}

	}

	function copyCID(cid) {
		console.log('Copying CID to clipboard')
		navigator.clipboard.writeText(cid)
		document.getElementById('copy-toast').classList.add('active')
		setTimeout(() => {
			document.getElementById('copy-toast').classList.remove('active')
		}, 2000)
	}

	return {
		view: () => (
		<div class="main">
			<div class="toast" id="copy-toast">
				<p> Copied CID to clipboard </p>
			</div>

			<div class="header">
				<h1 class='logo'> IPFS Huggingface mirror </h1>
			</div>

			<div class='top-bar'>
				<h1> Models </h1>
				<input class="search" type="text" placeholder="Search for models" oninput={(e) => searchTerm = e.target.value} />
			</div>


			<div className='content'>
				{Object.keys(models).length ? (
					<div class='model-list'>		
						{Object.entries(models).map(([key, value]) => (
							// Checks if the data isn't mallformed or if it's an API instead of a stored model
							key === 'cache' || !value.cache.ipfs["/"] || value.format === 'api' ? (
								null
							) : (
								// Checks if the search term matches the model name this is a really rudementary search
								key.toLowerCase().includes(searchTerm.toLowerCase()) ? (
								<div class='model-card' id={key}>
									<h2 class='model-name'> {key} </h2>
									<code class='codeblock' onclick={() => copyCID(value.cache.ipfs["/"].path)}>{value.cache.ipfs["/"].path} <i class="fa-solid fa-copy"></i> </code>
									<button onclick={() => revealModelDetails(key)}> <i class="fa-solid fa-angle-down"></i></button>
									<div class='model-details'>
										<div class="source">
											<p>Source: <a href={value.source} target="_blank" >{value.source}</a></p>
										</div>
										<div class="hw-reqs">
											<h3> Hardware requirements </h3>
											<ul>
												<li> Minimum T-flops: fp8 - {value.hwRequirements.minFlops.fp8}, fp16 - {value.hwRequirements.minFlops.fp16}, fp32 - {value.hwRequirements.minFlops.fp32} </li>
												<li> T-flops per unit: {value.hwRequirements.flopsPerUnit} </li>
												<li> GPU count: {value.hwRequirements.gpuCount.join(" - ")}</li>
												<li> CPU count: {value.hwRequirements.cpuCount.join(" - ")}</li>
												<li> GPU memory: {byteToGigaByte(value.hwRequirements.gpuMemory)} GB </li>
												<li> CPU memory: {byteToGigaByte(value.hwRequirements.cpuMemory)} GB </li>
												<li> Disk usage: {byteToGigaByte(value.hwRequirements.diskUsage)} GB </li>
											</ul>
										</div>
										<div class="metadata">
											<h3> Description </h3>
											<ul>
												<li> Conext size: {value.metadata.contextSize} </li>
												<li> Parameters: {value.metadata.parameters} </li>
												<li> Quantization: {value.metadata.quantization} </li>
												<li> Units: {value.metadata.units} </li>
											</ul>
										</div>										
									</div>
								</div>	
							) : (
								// I dont want to spam the console with this but mithril doesn't allow this to be empty
								null
							))
						))}
					</div>
  				) : (
					<span class="loader"></span>
  				)}
			</div>
		</div>
		)
	}
}

m.mount(document.body, Main)
