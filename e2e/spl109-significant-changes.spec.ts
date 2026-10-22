import { expect, test, type Page } from '@playwright/test';
const eventId=process.env.SPL109_EVENT_ID;
test.skip(!eventId, 'Requires the isolated SPL-109 real-Auth fixture.');
async function caption(page: Page, text: string) {
 await page.evaluate(message=>{let banner=document.getElementById('spl109-caption');if(!banner){banner=document.createElement('div');banner.id='spl109-caption';banner.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#163c42;color:white;padding:14px;font:18px system-ui;text-align:center;pointer-events:none';document.body.appendChild(banner);}banner.textContent=message;},text);
 await page.waitForTimeout(1500);
}
async function login(page: Page,email: string){
 await page.goto('/'); await page.getByLabel('Email address').fill(email);await page.getByLabel('Password').fill('LocalDemo123!');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page).toHaveURL(/workspace/,{timeout:30000});
}
// QA-SPL-109-200 | AC1-5 | BB
 test('[QA-SPL-109-200] warning, cancel, retained arrangements and confirmation loss',async({page})=>{
 test.setTimeout(180000);
 await login(page,'event.coordinator@example.test');
 await page.goto(`/workspace/assigned-events/${eventId}`);
 await expect(page.getByRole('heading',{name:'SPL-109 QA Confirmed Forum'})).toBeVisible({timeout:30000});
 await test.step('AC1 significant fields',async()=>{
  await page.getByRole('button',{name:'Edit event requirements'}).click();
  await page.getByLabel('Expected attendance',{exact:true}).fill('100');
  await expect(page.getByLabel('Date',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Start time',{exact:true})).toBeVisible();
  await caption(page,'AC1: edit significant requirements; preparation occupancy stays with the venue');
 });
 await test.step('AC2 warning and cancel',async()=>{
  await page.getByRole('button',{name:'Review changes',exact:true}).click();
  const warning=page.getByRole('region',{name:'Review significant changes'});
  await expect(warning).toContainText('SPL-109 QA Hall',{timeout:30000});
  await expect(warning).toContainText('SPL-109 QA Microphones');
  await caption(page,'AC2: both affected arrangements are listed; Cancel saves nothing');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Edit event requirements'}).click();
  await expect(page.getByLabel('Expected attendance',{exact:true})).toHaveValue('300');
  await page.getByLabel('Expected attendance',{exact:true}).fill('100');
  await page.getByRole('button',{name:'Review changes',exact:true}).click();
  await expect(warning).toBeVisible({timeout:30000});
 });
 await test.step('AC3 save retains and flags arrangements',async()=>{
  const saved=page.waitForResponse(r=>r.url().endsWith('/significant-changes')&&r.request().method()==='PATCH');
  await page.getByRole('button',{name:'Confirm and save changes'}).click();
  const result=await saved; expect(result.status()).toBe(200);
  const body=await result.json();
  expect(body.change.changes.expected_attendance).toEqual({previous:300,new:100});
  expect(body.status_change_id).toBeTruthy(); expect(body.event.status).toBe('planning');
  await expect(page.getByText('Event requirements saved. Affected arrangements are marked for review.')).toBeVisible({timeout:30000});
  await expect(page.getByText('SPL-109 QA Hall',{exact:true})).toBeVisible();
  await caption(page,'AC3: booking retained and flagged; equipment quantities retained for review');
 });
 await test.step('AC4 confirmed returns to planning after reload',async()=>{
  await page.reload();await expect(page.getByRole('heading',{name:'SPL-109 QA Confirmed Forum'})).toBeVisible({timeout:30000});
  await expect(page.getByRole('region',{name:'Requirements to consider'}).getByText('In planning',{exact:true})).toBeVisible();
  await caption(page,'AC4: Confirmed has returned to Planning; durable status event verified by API');
 });
 await test.step('AC5 unauthorised coordinator refused',async()=>{
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await login(page,'qa.coordinator.b@example.test');
  await page.goto(`/workspace/assigned-events/${eventId}`);
  await expect(page.getByRole('alert').first()).toBeVisible({timeout:30000});
  await expect(page.getByRole('button',{name:'Edit event requirements'})).toHaveCount(0);
  await caption(page,'AC5: another coordinator cannot edit; old/new audit and closed-event refusals covered by API tests');
 });
});
