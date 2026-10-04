const {execFileSync, spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const yaml = require('js-yaml');
const chart = process.argv[2];
const project = process.argv[3];
const config = JSON.parse(fs.readFileSync(path.join(project,'platform.json'),'utf8'));
for (const [name, app] of Object.entries(config.applications)) {
 const args=['template',name,chart,'-n','chart-test','-f',path.join(project,app.values)];
 const objects=yaml.loadAll(execFileSync('helm',args,{encoding:'utf8'})).filter(Boolean);
 assert.deepEqual(objects.map(o=>o.kind).sort(),['Deployment','Service']);
 for(const o of objects) {assert.equal(o.metadata.name,name);assert.equal(o.metadata.namespace,'chart-test');}
 const d=objects.find(o=>o.kind==='Deployment'), svc=objects.find(o=>o.kind==='Service');
 const pod=d.spec.template.spec,c=pod.containers[0];
 const values=yaml.load(fs.readFileSync(path.join(project,app.values),'utf8'));
 assert.deepEqual(svc.spec.selector,d.spec.selector.matchLabels);
 assert.equal(svc.spec.selector['app.kubernetes.io/instance'],name);
 assert.equal(pod.automountServiceAccountToken,false);
 assert.equal(pod.securityContext.runAsNonRoot,true);
 assert.equal(c.securityContext.readOnlyRootFilesystem,true);
 assert.equal(c.readinessProbe.httpGet.path,values.healthPath);
 assert.equal(svc.spec.ports[0].port,app.port);
 assert.ok(!c.command && !c.args);
 if(values.writableDirectory) assert.equal(pod.initContainers[0].image,c.image);
 else assert.ok(!pod.initContainers);
 for(const expected of values.env || []) assert.deepEqual(c.env.find(e=>e.name===expected.name),expected);
 const custom=yaml.loadAll(execFileSync('helm',[...args,'--set','replicas=2','--set-string','image=example/app:release'],{encoding:'utf8'})).find(o=>o?.kind==='Deployment');
 assert.equal(custom.spec.replicas,2);assert.equal(custom.spec.template.spec.containers[0].image,'example/app:release');
}
for(const value of ['replicas=0','port=65536','replicaz=2']) {
 const r=spawnSync('helm',['template','test',chart,'--set',value],{encoding:'utf8'});
 assert.notEqual(r.status,0);assert.match(r.stderr,/schema/);
}
console.log('PASS: shared chart release isolation, ports, probes, security, overrides and schema.');
