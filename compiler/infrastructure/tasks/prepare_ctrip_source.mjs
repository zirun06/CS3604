// Ctrip-only repairs for native roles, exact headings and nullable guest sessions.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
const workspace=resolve(process.argv[2]), mode=process.argv[3];
const ts=createRequire(resolve(workspace,'package.json'))('typescript');
const path=resolve(workspace,process.argv[4] || (mode==='backend'?'backend/src/api/register.ts':'frontend/src/App.tsx'));
let text=readFileSync(path,'utf8');
const program=mode==='frontend'?ts.createProgram([path],{target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,moduleResolution:ts.ModuleResolutionKind.NodeJs,strict:true,skipLibCheck:true,allowSyntheticDefaultImports:true}):null;
const file=program?.getSourceFile(path)||ts.createSourceFile(path,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
const checker=program?.getTypeChecker();
const edits=[];
const replace=(node,value)=>edits.push({start:node.getStart(file),end:node.end,value});
const insert=(position,value)=>edits.push({start:position,end:position,value});
function attr(node,name){return node.attributes.properties.find(n=>ts.isJsxAttribute(n)&&n.name.getText(file)===name);}
function literal(node){return node?.initializer&&ts.isStringLiteral(node.initializer)?node.initializer.text:null;}
function walk(node,visitor){visitor(node);ts.forEachChild(node,n=>walk(n,visitor));}
function walkValues(node,visitor){if(ts.isArrowFunction(node)||ts.isFunctionExpression(node)||ts.isFunctionDeclaration(node))return;visitor(node);ts.forEachChild(node,n=>walkValues(n,visitor));}
function regions(node){const found=[];for(let parent=node.parent;parent;parent=parent.parent)if(ts.isJsxElement(parent)){const label=literal(attr(parent.openingElement,'aria-label'));if(label)found.push(label);}return found;}
if(mode==='backend') {
  // Generated API middleware must not override the MIME type of HTML/static assets.
  for(const statement of file.statements)if(ts.isFunctionDeclaration(statement)&&statement.name?.text==='registerApis') {
    const app=statement.parameters[0]?.name.getText(file);
    walk(statement,node=>{
      if(!ts.isCallExpression(node)||!ts.isPropertyAccessExpression(node.expression)||node.expression.name.text!=='use'||node.expression.expression.getText(file)!==app)return;
      if(!node.arguments.length||!ts.isArrowFunction(node.arguments[0])&&!ts.isFunctionExpression(node.arguments[0]))return;
      let jsonHeader=false;
      for(const handler of node.arguments)walk(handler,call=>{
        if(!ts.isCallExpression(call)||!ts.isPropertyAccessExpression(call.expression))return;
        const method=call.expression.name.text,args=call.arguments;
        if(['setHeader','set','header'].includes(method)&&args[0]&&ts.isStringLiteral(args[0])&&args[0].text.toLowerCase()==='content-type'&&args[1]&&ts.isStringLiteral(args[1])&&/json/i.test(args[1].text))jsonHeader=true;
        if(['type','contentType'].includes(method)&&args[0]&&ts.isStringLiteral(args[0])&&/json/i.test(args[0].text))jsonHeader=true;
      });
      if(jsonHeader)insert(node.arguments[0].getStart(file),"'/api', ");
    });
  }
  // Only the guest/session resolver, not unrelated authorization SQL.
  const guestResolvers=new Set();
  for(const statement of file.statements) if(ts.isFunctionDeclaration(statement)&&/guest/i.test(statement.name?.text||''))
    walk(statement,node=>{if(ts.isCallExpression(node)&&ts.isIdentifier(node.expression))guestResolvers.add(node.expression.text);});
  for(const statement of file.statements) if(ts.isFunctionDeclaration(statement)&&guestResolvers.has(statement.name?.text)&&/session/i.test(statement.name?.text||'')) {
    walk(statement,node=>{
      if(!ts.isStringLiteral(node)&&!ts.isNoSubstitutionTemplateLiteral(node)) return;
      if(/\bfrom\s+sessions\s+\w+\s+join\s+users\b/i.test(node.text)) {
        const changed=node.text.replace(/(\bfrom\s+sessions\s+\w+\s+)join(\s+users\b)/i,'$1LEFT JOIN$2');
        replace(node,JSON.stringify(changed));
      }
    });
  }
  for(const statement of file.statements) if(ts.isFunctionDeclaration(statement)&&statement.name?.text==='clockNow'&&statement.body?.statements.length===1) {
    const returned=statement.body.statements[0];
    if(ts.isReturnStatement(returned)&&returned.expression&&ts.isIdentifier(returned.expression)&&!text.includes('ARC_CTRIP_CLOCK_STARTED')) {
      insert(statement.getStart(file),'const ARC_CTRIP_CLOCK_STARTED = Date.now();\n');
      replace(returned.expression,returned.expression.getText(file)+' + (Date.now() - ARC_CTRIP_CLOCK_STARTED)');
    }
  }
} else if(mode==='frontend') {
  // Synchronize persistent session consumers after successful authentication writes.
  // Only match a local fetch helper and mount-only effects that actually read session.
  const sessionEffects=[];
  for(const declaration of file.statements)if(ts.isFunctionDeclaration(declaration)&&declaration.body) {
    for(const statement of declaration.body.statements)walk(statement,node=>{
      if(!ts.isCallExpression(node)||!ts.isIdentifier(node.expression)||node.expression.text!=='useEffect')return;
      const deps=node.arguments[1],callback=node.arguments[0];
      if(!deps||!ts.isArrayLiteralExpression(deps)||deps.elements.length||!callback||!ts.isArrowFunction(callback))return;
      let sessionRead=false;
      walk(callback,n=>{if(ts.isCallExpression(n)&&n.arguments.some(a=>ts.isStringLiteral(a)&&a.text==='/api/session'))sessionRead=true;});
      if(sessionRead)sessionEffects.push({declaration,deps});
    });
  }
  const apiHelper=file.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='api'&&n.body&&n.parameters[0]&&ts.isIdentifier(n.parameters[0].name));
  let fetches=false;
  if(apiHelper)walk(apiHelper,n=>{if(ts.isCallExpression(n)&&ts.isIdentifier(n.expression)&&n.expression.text==='fetch')fetches=true;});
  if(apiHelper&&fetches&&sessionEffects.length&&!text.includes('arc:ctrip-session-changed')) {
    const parameter=apiHelper.parameters[0].name.text;
    for(const statement of apiHelper.body.statements)if(ts.isReturnStatement(statement))
      insert(statement.getStart(file),`if (/^\\/api\\/(?:login\\/(?:password|sms)|register\\/complete|logout)$/.test(${parameter})) window.dispatchEvent(new Event('arc:ctrip-session-changed'));\n`);
    const owners=new Set();
    for(const {declaration,deps} of sessionEffects) {
      replace(deps,'[arcCtripSessionVersion]');
      if(owners.has(declaration))continue;
      owners.add(declaration);
      insert(declaration.body.statements[0].getStart(file),`const [arcCtripSessionVersion, arcCtripSetSessionVersion] = useState(0);
  useEffect(() => { const refresh = () => arcCtripSetSessionVersion(v => v + 1); window.addEventListener('arc:ctrip-session-changed', refresh); return () => window.removeEventListener('arc:ctrip-session-changed', refresh); }, []);
  `);
    }
  }
  walk(file,node=>{
    // React boolean props commonly receive string && condition ('' | boolean).
    // Preserve JS truthiness while avoiding a whole frontend regeneration.
    if(ts.isJsxExpression(node)&&node.expression&&ts.isJsxAttribute(node.parent)&&['disabled','checked','required','readOnly','multiple','hidden','autoFocus'].includes(node.parent.name.getText(file))) {
      const type=checker.getTypeAtLocation(node.expression),types=type.isUnion()?type.types:[type];
      if(types.some(t=>!!(t.flags&ts.TypeFlags.BooleanLike))&&types.some(t=>!!(t.flags&ts.TypeFlags.StringLike))&&types.every(t=>!!(t.flags&(ts.TypeFlags.BooleanLike|ts.TypeFlags.StringLike|ts.TypeFlags.Null|ts.TypeFlags.Undefined))))replace(node.expression,'Boolean('+node.expression.getText(file)+')');
    }
    // A visible scalar is its own DOM text boundary, without changing text or data.
    // Type checking excludes JSX, lists, objects and unknown values from wrapping.
    if(ts.isJsxExpression(node)&&node.expression&&ts.isJsxElement(node.parent)&&['span','div','p','li','td','dd','dt'].includes(node.parent.openingElement.tagName.getText(file))) {
      const siblings=node.parent.children;
      const mixed=siblings.some(n=>n!==node&&(ts.isJsxText(n)?n.text.trim():true));
      const type=checker.getTypeAtLocation(node.expression);
      const types=type.isUnion()?type.types:[type];
      const scalar=types.every(t=>!!(t.flags&(ts.TypeFlags.StringLike|ts.TypeFlags.NumberLike|ts.TypeFlags.Null|ts.TypeFlags.Undefined)))&&types.some(t=>!!(t.flags&(ts.TypeFlags.StringLike|ts.TypeFlags.NumberLike)));
      if(mixed&&scalar){insert(node.getStart(file),'<span>');insert(node.end,'</span>');}
    }
    if(ts.isJsxSelfClosingElement(node)&&node.tagName.getText(file)==='input'&&!attr(node,'onClick')&&['Departure date','Return date'].includes(literal(attr(node,'aria-label')))) {
      // Reuse the existing sibling picker trigger; never invent dates or state names.
      let field=node.parent;
      if(ts.isJsxElement(field)&&field.openingElement.tagName.getText(file)==='label')field=field.parent;
      const triggers=[];
      if(field&&ts.isJsxElement(field))for(const child of field.children)if(ts.isJsxElement(child)&&child.openingElement.tagName.getText(file)==='button'&&child.children.filter(ts.isJsxText).map(n=>n.text.trim()).join(' ')==='Choose date') {
        const click=attr(child.openingElement,'onClick');if(click)triggers.push(click);
      }
      if(triggers.length===1)insert(node.tagName.end,' '+triggers[0].getText(file));
    }
    if(!ts.isJsxElement(node)) return;
    const opening=node.openingElement,tag=opening.tagName.getText(file);
    const name=node.children.filter(ts.isJsxText).map(n=>n.text.trim()).join(' ').trim();
    const role=attr(opening,'role');
    const scopes=regions(node);
    if(['div','li','tr'].includes(tag)&&scopes.includes('City buses')&&!attr(opening,'aria-label')) {
      const identities=new Set();
      walkValues(node,n=>{if(ts.isJsxExpression(n)&&n.expression&&ts.isPropertyAccessExpression(n.expression)&&n.expression.name.text==='name')identities.add(n.expression.getText(file));});
      if(identities.size===1){insert(opening.tagName.end," aria-label={'Record ' + "+[...identities][0]+"}");if(tag==='div'&&!role)insert(opening.tagName.end,' role="group"');}
    }
    if(['Link','NavLink','a'].includes(tag)&&name==='View details'&&scopes.includes('Order list')&&!role)insert(opening.tagName.end,' role="button"');
    if(tag==='li'&&scopes.some(n=>['Pending vouchers','Completed vouchers'].includes(n))&&!attr(opening,'aria-label')) {
      const identities=new Map();
      walkValues(node,n=>{if(ts.isJsxExpression(n)&&n.expression&&ts.isPropertyAccessExpression(n.expression)&&n.expression.name.text==='number')identities.set(n.expression.getText(file),n.expression);});
      if(identities.size===1)insert(opening.tagName.end," aria-label={'Record ' + "+[...identities.keys()][0]+"}");
    }
    if(tag==='button'&&scopes.some(n=>['Popular airports','Domestic airports','Today weather'].includes(n))&&(!role||literal(role)==='button')) {
      const click=attr(opening,'onClick'),callback=click?.initializer&&ts.isJsxExpression(click.initializer)?click.initializer.expression:null;
      const call=callback&&ts.isArrowFunction(callback)&&ts.isCallExpression(callback.body)?callback.body:null;
      let owner=node.parent;while(owner&&(!ts.isFunctionDeclaration(owner)&&!ts.isArrowFunction(owner)||!owner.body||!ts.isBlock(owner.body)))owner=owner.parent;
      const routerNames=new Set();
      if(owner?.body&&ts.isBlock(owner.body))for(const statement of owner.body.statements)if(ts.isVariableStatement(statement))for(const declaration of statement.declarationList.declarations)
        if(ts.isIdentifier(declaration.name)&&declaration.initializer&&ts.isCallExpression(declaration.initializer)&&declaration.initializer.expression.getText(file)==='useNavigate')routerNames.add(declaration.name.text);
      const importsLink=file.statements.some(s=>ts.isImportDeclaration(s)&&s.moduleSpecifier.text==='react-router-dom'&&s.importClause?.namedBindings&&ts.isNamedImports(s.importClause.namedBindings)&&s.importClause.namedBindings.elements.some(n=>n.name.text==='Link'));
      if(call&&ts.isIdentifier(call.expression)&&routerNames.has(call.expression.text)&&call.arguments.length===1&&importsLink) {
        replace(opening.tagName,'Link');replace(node.closingElement.tagName,'Link');replace(click,'to={'+call.arguments[0].getText(file)+'}');
        const type=attr(opening,'type');if(type)replace(type,'');if(role)replace(role,'');
      }
    }
    if(literal(role)==='menuitem'&&['Link','NavLink','a','button'].includes(tag)&&name!=='Log out') replace(role,'');
    if(['Link','NavLink','a','button'].includes(tag)&&name==='Log out'&&!role)insert(opening.tagName.end,' role="menuitem"');
    if(tag==='button'&&literal(role)==='tab'&&['Verification code login','Password login'].includes(name)) {
      // These two switches are links in the product contract; preserve their handler.
      replace(role,'role="link"');
    }
    if(/^h[1-6]$/.test(tag)&&name==='Book flight') {
      if(!attr(opening,'aria-label'))insert(opening.tagName.end,' aria-label="Book flight"');
      for(const child of node.children)if(ts.isJsxExpression(child)&&child.expression){insert(child.getStart(file),'<span>');insert(child.end,'</span>');}
    }
    if(['Link','NavLink','a'].includes(tag)&&name==='More services') {
      let parent=node.parent,global=false;
      while(parent){if(ts.isJsxElement(parent)&&literal(attr(parent.openingElement,'aria-label'))==='Global navigation')global=true;parent=parent.parent;}
      if(!global) for(const child of node.children) if(ts.isJsxText(child)&&child.text.trim()==='More services') replace(child,'Explore more services');
    }
    if(tag==='main') {
      let flightList=false,hasHeading=false;
      walk(node,child=>{if(ts.isJsxOpeningElement(child)||ts.isJsxSelfClosingElement(child)) {
        if(literal(attr(child,'aria-label'))==='Flight list')flightList=true;
        if(child.tagName.getText(file)==='h1')hasHeading=true;
      }});
      if(flightList&&!hasHeading)insert(opening.end,'<h1>Flight results</h1>');
    }
    let inGlobalNav=false;
    for(let parent=node.parent;parent;parent=parent.parent)if(ts.isJsxElement(parent)&&literal(attr(parent.openingElement,'aria-label'))==='Global navigation')inGlobalNav=true;
    // CSS pseudo-element arrows participate in accessible names unless the real
    // menu label is explicit, including reusable Dropdown(label) implementations.
    if(tag==='button'&&!attr(opening,'aria-label')) {
      const expressions=node.children.filter(n=>ts.isJsxExpression(n)&&n.expression);
      if(inGlobalNav&&['Flights','More services','My account','Log out'].includes(name)&&!expressions.length)insert(opening.tagName.end,' aria-label='+JSON.stringify(name));
      else if(literal(attr(opening,'aria-haspopup'))==='menu'&&expressions.length===1) {
        const value=expressions[0].expression,type=checker.getTypeAtLocation(value);
        if(type.flags&ts.TypeFlags.StringLike)insert(opening.tagName.end,' aria-label={'+value.getText(file)+'}');
      }
    }
    if(tag==='button'&&(name==='My account'||inGlobalNav&&['Flights','More services'].includes(name)||literal(attr(opening,'aria-haspopup'))==='menu')) {
      const click=attr(opening,'onClick');let ancestor=node.parent;
      let owner=node.parent;while(owner&&!ts.isFunctionDeclaration(owner)&&!ts.isArrowFunction(owner))owner=owner.parent;
      const handlers=new Map();
      if(owner?.body&&ts.isBlock(owner.body))for(const statement of owner.body.statements)if(ts.isVariableStatement(statement))for(const declaration of statement.declarationList.declarations)
        if(ts.isIdentifier(declaration.name)&&declaration.initializer&&ts.isArrowFunction(declaration.initializer))handlers.set(declaration.name.text,declaration.initializer);
      const handler=value=>value&&ts.isJsxExpression(value)&&value.expression&&ts.isIdentifier(value.expression)?handlers.get(value.expression.text)||value:value;
      if(click?.initializer&&ts.isJsxExpression(click.initializer))walk(handler(click.initializer),call=>{
        if(!ts.isCallExpression(call)||call.arguments.length!==1)return;
        const arg=call.arguments[0];
        if(!ts.isArrowFunction(arg)||!ts.isPrefixUnaryExpression(arg.body)||arg.body.operator!==ts.SyntaxKind.ExclamationToken)return;
        let hoverOpens=false;
        for(let parent=node;parent;parent=parent.parent)if(ts.isJsxElement(parent)) {
          for(const event of ['onMouseEnter','onPointerEnter']) {
            const hover=attr(parent.openingElement,event);
            if(hover?.initializer)walk(handler(hover.initializer),h=>{if(ts.isCallExpression(h)&&h.expression.getText(file)===call.expression.getText(file)&&h.arguments[0]?.kind===ts.SyntaxKind.TrueKeyword)hoverOpens=true;});
          }
        }
        if(hoverOpens)replace(arg,'true');
      });
    }
  });
} else throw new Error('Expected backend or frontend');
for(const edit of edits.sort((a,b)=>b.start-a.start))text=text.slice(0,edit.start)+edit.value+text.slice(edit.end);
if(edits.length)writeFileSync(path,text);
console.log(JSON.stringify({mode,changes:edits.length}));
