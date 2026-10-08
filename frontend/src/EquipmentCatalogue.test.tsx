import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EquipmentCatalogue } from './EquipmentCatalogue';

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const microphone = {
  id: 1,
  name: 'Wireless Microphone',
  description: 'Handheld wireless microphone.',
  location: 'Technical Store A',
  total_stock: 12,
};

describe('EquipmentCatalogue', () => {
  // SPL-94 AC-1 / TC-SPL-94-008: Technical Support can add an inventory type through the UI.
  it('creates an equipment type and refreshes the catalogue', async () => {
    let created = false;
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/equipment-types' && !init) {
        return response({ equipment_types: created ? [microphone] : [] });
      }
      if (path === '/api/equipment-types' && init?.method === 'POST') {
        expect(JSON.parse(String(init.body))).toEqual({
          name: 'Wireless Microphone', description: 'Handheld wireless microphone.',
          location: 'Technical Store A', total_stock: 12,
        });
        created = true;
        return response({ equipment_type: microphone }, 201);
      }
      return response({});
    });
    render(<EquipmentCatalogue accessToken="fixture" request={request} />);

    await screen.findByText('No equipment types yet');
    fireEvent.change(screen.getByLabelText('Equipment type name'), { target: { value: microphone.name } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: microphone.description } });
    fireEvent.change(screen.getByLabelText('Storage location'), { target: { value: microphone.location } });
    fireEvent.change(screen.getByLabelText('Total units in stock'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add equipment type' }));

    expect(await screen.findByText('Equipment type added to the catalogue.')).toBeTruthy();
    expect(await screen.findByText('Wireless Microphone')).toBeTruthy();
  });

  // SPL-94 AC-1 / TC-SPL-94-009: malformed stock is stopped by native field constraints.
  it('keeps an invalid negative stock value from reaching the API', async () => {
    const request = vi.fn(async () => response({ equipment_types: [] }));
    render(<EquipmentCatalogue accessToken="fixture" request={request} />);

    await screen.findByText('No equipment types yet');
    fireEvent.change(screen.getByLabelText('Equipment type name'), { target: { value: 'Projector' } });
    const stock = screen.getByLabelText('Total units in stock');
    fireEvent.change(stock, { target: { value: '-1' } });
    fireEvent.invalid(stock);
    expect(await screen.findByText('Total stock must be a whole number of zero or more.')).toBeTruthy();
    fireEvent.submit(screen.getByRole('button', { name: 'Add equipment type' }).closest('form')!);

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  });

  // SPL-94 AC-1 / TC-SPL-94-010: the staff editor submits an intentional stock change.
  it('edits an existing equipment type', async () => {
    const request = vi.fn(async (path: string, init?: RequestInit) => {
      if (path === '/api/equipment-types' && !init) return response({ equipment_types: [microphone] });
      if (path === '/api/equipment-types/1' && init?.method === 'PATCH') return response({ equipment_type: { ...microphone, total_stock: 16 } });
      return response({ equipment_types: [{ ...microphone, total_stock: 16 }] });
    });
    render(<EquipmentCatalogue accessToken="fixture" request={request} />);

    await screen.findByText('Wireless Microphone');
    fireEvent.click(screen.getByRole('button', { name: 'Edit Wireless Microphone' }));
    fireEvent.change(screen.getByLabelText('Total units in stock'), { target: { value: '16' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByText('Equipment type updated.')).toBeTruthy();
    expect(request).toHaveBeenCalledWith('/api/equipment-types/1', expect.objectContaining({ method: 'PATCH' }));
  });
});
