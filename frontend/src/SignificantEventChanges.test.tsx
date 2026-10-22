import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SignificantEventChanges } from './SignificantEventChanges';

const event = {id: 109, status: 'confirmed', proposed_date: '2030-06-15', start_time: '10:00', end_time: '12:00', expected_attendance: 300, required_facilities: ['Projector'], accessibility_needs: ['Step-free access']};
const impact = {preview_token: 'checked', changes: {expected_attendance: {previous: 300, new: 100}}, arrangements: [{kind: 'venue', id: 1, name: 'QA hall', reason: 'Attendance no longer covers booking. Booking retained.'}, {kind: 'equipment', id: 2, name: 'Microphones', reason: 'Review required; quantities retained.'}], returns_to_planning: true};
const response = (body: unknown, status=200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type':'application/json'}});
afterEach(cleanup);
function setup() {
 const api=vi.fn(); const onSaved=vi.fn();
 render(<SignificantEventChanges event={event} api={api} onSaved={onSaved}/>);
 fireEvent.click(screen.getByRole('button',{name:'Edit event requirements'}));
 fireEvent.change(screen.getByLabelText('Expected attendance'),{target:{value:'100'}});
 return {api,onSaved};
}
describe('SPL-109 warning flow',()=>{
 // QA-SPL-109-030 | AC2 | BB
 it('[QA-SPL-109-030] lists each impact and cancel sends no save',async()=>{
  const {api,onSaved}=setup(); api.mockResolvedValueOnce(response(impact));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  await screen.findByRole('region',{name:'Review significant changes'});
  expect(screen.getByText(/QA hall/)).toBeTruthy(); expect(screen.getByText(/Microphones/)).toBeTruthy();
  expect(screen.getByText(/return from Confirmed to Planning/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
  expect(api).toHaveBeenCalledTimes(1); expect(onSaved).not.toHaveBeenCalled();
 });
 // QA-SPL-109-031 | AC4 | BB
 it('[QA-SPL-109-031] confirms with token and refreshes saved state',async()=>{
  const {api,onSaved}=setup(); const updated={...event,status:'planning',expected_attendance:100};
  api.mockResolvedValueOnce(response(impact)).mockResolvedValueOnce(response({event:updated,change:{id:1}}));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  fireEvent.click(await screen.findByRole('button',{name:'Confirm and save changes'}));
  await waitFor(()=>expect(onSaved).toHaveBeenCalledWith(updated));
  expect(api.mock.calls[1][1].method).toBe('PATCH');
  expect(JSON.parse(api.mock.calls[1][1].body).preview_token).toBe('checked');
 });
 // QA-SPL-109-032 | AC2 | BB
 it('[QA-SPL-109-032] going back requires a fresh preview',async()=>{
  const {api}=setup(); api.mockResolvedValueOnce(response(impact));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  fireEvent.click(await screen.findByRole('button',{name:'Back to editing'}));
  expect(screen.queryByRole('button',{name:'Confirm and save changes'})).toBeNull();
  expect((screen.getByLabelText('Expected attendance') as HTMLInputElement).disabled).toBe(false);
 });
 // QA-SPL-109-033 | AC5 | BB
 it('[QA-SPL-109-033] stale save shows refusal and requires new preview',async()=>{
  const {api,onSaved}=setup(); api.mockResolvedValueOnce(response(impact)).mockResolvedValueOnce(response({error:'The event changed. Review again.'},409));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  fireEvent.click(await screen.findByRole('button',{name:'Confirm and save changes'}));
  await screen.findByRole('alert'); expect(onSaved).not.toHaveBeenCalled();
  expect(screen.queryByRole('button',{name:'Confirm and save changes'})).toBeNull();
 });
 // QA-SPL-109-034 | AC4 | BB
 it('[QA-SPL-109-034] no-op refreshes current state without saving',async()=>{
  const {api,onSaved}=setup(); const current={...event,status:'planning'};
  api.mockResolvedValueOnce(response({...impact,changes:{},arrangements:[],event:current}));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  await waitFor(()=>expect(onSaved).toHaveBeenCalledWith(current)); expect(api).toHaveBeenCalledTimes(1);
 });
 // QA-SPL-109-035 | AC2 | BB
 it('[QA-SPL-109-035] network failure preserves editable values',async()=>{
  const {api}=setup(); api.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(screen.getByRole('button',{name:'Review changes'}));
  await screen.findByRole('alert'); expect((screen.getByLabelText('Expected attendance') as HTMLInputElement).value).toBe('100');
 });
 // QA-SPL-109-036 | AC1 | BB
 it('[QA-SPL-109-036] exposes significant fields without preparation occupancy',()=>{
  setup(); for(const name of ['Date','Start time','End time','Preferred room layout','Required facilities (comma-separated)','Accessibility needs (comma-separated)']) expect(screen.getByLabelText(name)).toBeTruthy();
  expect(screen.queryByLabelText(/preparation|setup minutes/i)).toBeNull();
 });
});
