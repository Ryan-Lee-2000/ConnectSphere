import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiRequest } from './api';
import { ChangeRequestItems, ChangeRequestsPanel } from './ChangeRequests';

afterEach(cleanup);
const choices = { equipment_types: [{id:1,name:'Projector'}], equipment_requirements: [{requirement_id:1,equipment_type:'Custom microphone',quantity:3,notes:'Wireless'}] };
function setup(options: unknown = choices) {
 const api = vi.fn(async (url: string, init?: RequestInit) => ({ok:true,status:init?.method==='POST'?201:200,json:async()=>url.endsWith('equipment-options')?options:{change_requests:[]}}));
 render(<ChangeRequestsPanel api={api as unknown as ApiRequest} eventId={12} eventStatus="planning" canSubmit />);
 return api;
}
async function open(action='equipment_add') {
 fireEvent.click(await screen.findByRole('button',{name:'Request a change'}));
 fireEvent.change(screen.getByLabelText('Field to change'),{target:{value:action}});
 await screen.findByLabelText(action==='equipment_add'?'Equipment type':'Current equipment requirement');
}
function choose(label: string,value: string) {fireEvent.change(screen.getByLabelText(label),{target:{value}});}

// QA-SPL-141-101 | AC1 | BB
it('[QA-SPL-141-101] catalogue add sends a separate proposal without copying same-ID line values',async()=>{
 const api=setup();await open();choose('Equipment type','1');
 expect((screen.getByLabelText('Proposed quantity') as HTMLInputElement).value).toBe('');
 choose('Proposed quantity','4');choose('Proposed technical notes (optional)','HDMI');choose('Reason','More screens');
 fireEvent.click(screen.getByRole('button',{name:'Submit change request'}));
 await waitFor(()=>expect(api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));
 const post=api.mock.calls.find(([,init])=>init?.method==='POST')!;
 expect(JSON.parse(post[1]!.body as string).items).toEqual([{field:'equipment',requested_value:{operation:'add',equipment_type_id:1,quantity:4,notes:'HDMI'},reason:'More screens'}]);
});

// QA-SPL-141-102 | AC1 | BB
it('[QA-SPL-141-102] changing notes starts with the current unmapped values',async()=>{
 const api=setup();await open('equipment_update');choose('Current equipment requirement','1');
 expect((screen.getByLabelText('Proposed quantity') as HTMLInputElement).value).toBe('3');
 expect(screen.getByText('Now: Custom microphone · Quantity: 3 · Notes: Wireless')).toBeTruthy();
 choose('Proposed technical notes (optional)','');choose('Reason','Clear note');
 fireEvent.click(screen.getByRole('button',{name:'Submit change request'}));
 await waitFor(()=>expect(api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));
 const post=api.mock.calls.find(([,init])=>init?.method==='POST')!;
 expect(JSON.parse(post[1]!.body as string).items[0].requested_value).toEqual({operation:'update',requirement_id:1,quantity:3,notes:null});
});

// QA-SPL-141-103 | AC1 | BB
it('[QA-SPL-141-103] removal sends only the selected line and action',async()=>{
 const api=setup();await open('equipment_remove');choose('Current equipment requirement','1');choose('Reason','Not needed');
 expect(screen.queryByLabelText('Proposed quantity')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Submit change request'}));
 await waitFor(()=>expect(api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));
 const post=api.mock.calls.find(([,init])=>init?.method==='POST')!;
 expect(JSON.parse(post[1]!.body as string).items[0].requested_value).toEqual({operation:'remove',requirement_id:1});
});

// QA-SPL-141-104 | AC2 | BB
it('[QA-SPL-141-104] renders readable old/new quantity, notes and removal',()=>{
 render(<ChangeRequestItems items={[{id:1,field:'equipment:line:1',field_label:'Equipment requirement',current_value:{equipment_type:'Mic',quantity:3,notes:'Wireless'},requested_value:{equipment_type:'Mic',quantity:5,notes:null},reason:'More guests'},{id:2,field:'equipment:line:2',field_label:'Equipment requirement',current_value:{equipment_type:'Screen',quantity:1,notes:null},requested_value:{operation:'remove',requirement_id:2},reason:'Not needed'}]} />);
 expect(screen.getByText('Now: Mic · Quantity: 3 · Notes: Wireless')).toBeTruthy();
 expect(screen.getByText('Requested: Mic · Quantity: 5 · Notes: None')).toBeTruthy();
 expect(screen.getByText('Requested: Remove this requirement')).toBeTruthy();
});

// QA-SPL-141-105 | AC3 | BB
it('[QA-SPL-141-105] missing quantity is refused without submitting',async()=>{
 const api=setup();await open();choose('Equipment type','1');choose('Reason','More screens');
 fireEvent.click(screen.getByRole('button',{name:'Submit change request'}));
 expect(await screen.findByRole('alert')).toBeTruthy();
 expect(api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
 const quantity=screen.getByLabelText('Proposed quantity') as HTMLInputElement;
 expect(quantity.min).toBe('1');expect(quantity.step).toBe('1');
});

// QA-SPL-141-106 | AC1 | BB
it('[QA-SPL-141-106] empty catalogue and current-lines states are explicit',async()=>{
 setup({equipment_types:[],equipment_requirements:[]});await open();
 expect(screen.getByText('No equipment types are available in the catalogue.')).toBeTruthy();
 choose('Field to change','equipment_update');
 expect(screen.getByText('This event has no current equipment requirements to change.')).toBeTruthy();
});

// QA-SPL-141-107 | AC1 | BB
it('[QA-SPL-141-107] equipment load failure can be retried',async()=>{
 let attempts=0;
 const api=vi.fn(async(url:string)=>{if(url.endsWith('equipment-options') && attempts++===0)throw new Error('Offline');return {ok:true,status:200,json:async()=>url.endsWith('equipment-options')?choices:{change_requests:[]}};});
 render(<ChangeRequestsPanel api={api as unknown as ApiRequest} eventId={12} eventStatus="planning" canSubmit />);
 fireEvent.click(await screen.findByRole('button',{name:'Request a change'}));choose('Field to change','equipment_add');
 fireEvent.click(await screen.findByRole('button',{name:'Retry equipment choices'}));
 expect(await screen.findByLabelText('Equipment type')).toBeTruthy();expect(attempts).toBe(2);
});
