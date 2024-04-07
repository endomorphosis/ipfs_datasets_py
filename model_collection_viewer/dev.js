import fs from 'fs'
import Koa from 'koa'
import serve from 'koa-static'
import esbuild from 'esbuild'
import postcss from 'postcss'
import postcssImport from 'postcss-import'
import postcssUnnest from 'postcss-nested'
import chokidar from 'chokidar'


let koa = new Koa()
koa.use(serve('.'))
koa.listen(5173)

if(!fs.existsSync('dist'))
	fs.mkdirSync('dist')


let postcssCompiler = postcss([
	postcssImport,
	postcssUnnest
])

function compileCss(){
	console.log('compiling css...')

	postcssCompiler.process(fs.readFileSync('./src/style.scss', 'utf-8'), { map: false, from: '.' })
		.then(({ css, messages }) => {
			fs.writeFileSync('./dist/app.css', css)

			for(let message of messages){
				log.warn(message)
			}

			console.log('css compiled successfully')
		})
		.catch(error => {
			console.error('css error:', error)
		})
}

compileCss()

let ctx = await esbuild.context({
	entryPoints: ['./src/app.jsx'],
	jsxFactory: 'm',
	jsxFragment: '\'[\'',
	outdir: './dist',
	bundle: true
})

chokidar.watch(['./src/style.scss']).on('change', path => {
	console.log(`stylesheet changed`)
	compileCss()
})

await ctx.watch()