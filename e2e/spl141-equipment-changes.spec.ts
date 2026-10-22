import { expect, test, type Page } from '@playwright/test';
const eventId=process.env.SPL141_EVENT_ID;
const kind=process.env.SPL141_TYPE_ID;
const mapped=process.env.SPL141_MAPPED_ID;
const custom=process.env.SPL141_CUSTOM_ID;
test.skip(!eventId || !kind || !mapped || !custom,'Requires isolated SPL-141 real-Auth UAT fixture.');
async function caption(page:Page,text:string){
 await page.evaluate(message=>{let el=document.getElementById('qa-caption');if(!el){el=document.createElement('div');el.id='qa-caption';el.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#163c42;color:white;padding:14px;font:18px system-ui;text-align:center;pointer-events:none';document.body.appendChild(el);}el.textContent=message;},text);
 await page.waitForTimeout(1800);
}
async function login(page:Page,email:string,organiser=false){
 await page.goto('/');await page.getByLabel('Email address').fill(email);await page.getByLabel('Password').fill('LocalDemo123!');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).toHaveURL(/workspace/,{timeout:30000});
 if(organiser)await page.getByRole('button',{name:/^Event Organiser/}).click();
 await expect(page.getByRole('navigation',{name:'Workspace'})).toBeVisible({timeout:30000});
}
// QA-SPL-141-200 | AC1-5 | BB
test('[QA-SPL-141-200] equipment proposals retain actual lines and reservations',async({page})=>{
 test.setTimeout(180000);
 let auth='';page.on('request',r=>{if(r.url().includes('/api/')&&r.headers()['authorization'])auth=r.headers()['authorization'];});
 await login(page,'developer@example.test',true);await page.getByRole('link',{name:'My requests',exact:true}).click();
 const row=page.getByRole('row').filter({hasText:process.env.SPL141_EVENT_NAME ?? 'SPL-141 QA Equipment Forum'});
 await expect(row).toBeVisible({timeout:30000});await row.getByRole('button',{name:'Change requests'}).click();await page.getByRole('button',{name:'Request a change'}).click();
 await test.step('AC1 propose add, quantity/notes update and removal',async()=>{
  await page.getByLabel('Field to change').selectOption('equipment_add');await page.getByRole('combobox',{name:'Equipment type',exact:true}).selectOption(kind!);await page.getByLabel('Proposed quantity').fill('4');await page.getByLabel('Proposed technical notes (optional)').fill('Extra screen');await page.getByLabel('Reason').fill('More screens');
  await page.getByRole('button',{name:'Add another item'}).click();await page.getByLabel('Field to change').nth(1).selectOption('equipment_update');await page.getByLabel('Current equipment requirement').selectOption(custom!);await page.getByLabel('Proposed quantity').nth(1).fill('5');await page.getByLabel('Proposed technical notes (optional)').nth(1).fill('Five wireless microphones');await page.getByLabel('Reason').nth(1).fill('Larger panel');
  await page.getByRole('button',{name:'Add another item'}).click();await page.getByLabel('Field to change').nth(2).selectOption('equipment_remove');await page.getByLabel('Current equipment requirement').nth(1).selectOption(mapped!);await page.getByLabel('Reason').nth(2).fill('Replace original projector');
  await caption(page,'AC1: separate add, quantity/notes change and removal proposals');
 });
 await test.step('AC2 compare current line and proposed values',async()=>{
  await expect(page.getByText('Now: SPL-141 Custom microphones · Quantity: 3 · Notes: Wireless')).toBeVisible();
  await expect(page.getByLabel('Proposed quantity').nth(1)).toHaveValue('5');
  await caption(page,'AC2: current microphone quantity 3; proposed quantity 5 and new technical notes');
 });
 await test.step('AC3 refuse zero quantity then submit valid items',async()=>{
  await page.getByLabel('Proposed quantity').first().fill('0');await page.getByRole('button',{name:'Submit change request'}).click();
  expect(await page.getByLabel('Proposed quantity').first().evaluate(el=>(el as HTMLInputElement).validity.rangeUnderflow)).toBe(true);
  await expect(page.getByRole('form',{name:'New change request'})).toBeVisible();
  await caption(page,'AC3: quantity zero is refused; no request has been submitted');
  await page.getByLabel('Proposed quantity').first().fill('4');
  const response=page.waitForResponse(r=>r.url().endsWith('/change-requests')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Submit change request'}).click();expect((await response).status()).toBe(201);
  const pending=page.getByRole('group',{name:'Pending change request'});await expect(pending).toBeVisible({timeout:30000});await expect(pending.getByRole('listitem')).toHaveCount(3);
  await expect(pending).toContainText('Requested: Remove this requirement');await expect(pending).toContainText('Quantity: 5');
 });
 await test.step('AC4 a role without organiser permission cannot access proposals',async()=>{
  await page.getByRole('button',{name:'Sign out',exact:true}).click();await login(page,'attendee@example.test');
  await expect(page.getByRole('link',{name:'My requests',exact:true})).toHaveCount(0);
  const denied=await page.request.get(`/api/event-requests/${eventId}/change-requests`,{headers:{Authorization:auth}});expect(denied.status()).toBe(403);
  await caption(page,'AC4: attendee has no change-request action; API refuses access (403)');
 });
 await test.step('AC5 coordinator sees unchanged actual equipment after submission',async()=>{
  await page.getByRole('button',{name:'Sign out',exact:true}).click();await login(page,'event.coordinator@example.test');
  await page.goto(`/workspace/assigned-events/${eventId}/equipment-requirements`);
  const active=page.getByRole('region',{name:'Active equipment requirements'});await expect(active).toBeVisible({timeout:30000});
  await expect(active.getByRole('article')).toHaveCount(2);
  const original=active.getByRole('article').filter({hasText:'SPL-141 QA Projector'});await expect(original).toContainText(/reserved/i);await expect(original.locator('dd').first()).toHaveText('2');
  const microphones=active.getByRole('article').filter({hasText:'SPL-141 Custom microphones'});await expect(microphones.locator('dd').first()).toHaveText('3');
  await caption(page,'AC5: actual lines remain 2 projectors (Reserved) and 3 microphones; proposals await SPL-112');
 });
});
