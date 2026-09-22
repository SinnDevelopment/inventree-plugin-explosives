import {
  checkPluginVersion,
  type InvenTreePluginContext
} from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  List,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import {
  errorMessages,
  fetchJson,
  kg,
  type PartExplosive,
  type PartExplosiveUpdate,
  patchPart,
  urls
} from './api';

/** A mass value in kg rendered as a string for a text input. */
function massInput(value: number | null): string {
  return value === null || value === undefined ? '' : String(value);
}

interface FormState {
  neq: string;
  gross: string;
  division: string;
  compatibility_group: string;
  un_number: string;
  proper_shipping_name: string;
}

function toForm(data: PartExplosive): FormState {
  return {
    neq: massInput(data.neq_per_unit_kg),
    gross: massInput(data.gross_mass_per_unit_kg),
    division: data.division ?? '',
    compatibility_group: data.compatibility_group ?? '',
    un_number: data.un_number ?? '',
    proper_shipping_name: data.proper_shipping_name ?? ''
  };
}

/** The editable explosive-data form for a part already flagged explosive. */
function EditForm({
  context,
  partId,
  data
}: {
  context: InvenTreePluginContext;
  partId: number | string;
  data: PartExplosive;
}) {
  const [form, setForm] = useState<FormState>(() => toForm(data));
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // Re-sync when the server data changes (e.g. after a save refetch).
  useEffect(() => {
    setForm(toForm(data));
    setErrors([]);
  }, [data]);

  const refresh = () =>
    context.queryClient.invalidateQueries({
      queryKey: ['explosives-part', partId]
    });

  const set = (key: keyof FormState) => (value: string | null) =>
    setForm((f) => ({ ...f, [key]: value ?? '' }));

  const save = async () => {
    setSaving(true);
    setErrors([]);

    const payload: PartExplosiveUpdate = {
      neq_per_unit_kg: form.neq.trim(),
      gross_mass_per_unit_kg: form.gross.trim(),
      division: form.division,
      compatibility_group: form.compatibility_group,
      un_number: form.un_number.trim(),
      proper_shipping_name: form.proper_shipping_name.trim()
    };

    try {
      await patchPart(context, partId, payload);
      await refresh();
      notifications.show({
        title: 'Saved',
        message: 'Explosive data updated.',
        color: 'green'
      });
    } catch (error) {
      const detail = (error as { response?: { data?: unknown } })?.response
        ?.data;
      setErrors(errorMessages(detail));
    } finally {
      setSaving(false);
    }
  };

  const unmark = async () => {
    setSaving(true);
    try {
      await patchPart(context, partId, { is_explosive: false });
      await refresh();
    } catch (error) {
      const detail = (error as { response?: { data?: unknown } })?.response
        ?.data;
      setErrors(errorMessages(detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Stack gap='md'>
      {data.issues.length > 0 ? (
        <Alert color='orange' title='Data integrity issues'>
          <List size='sm'>
            {data.issues.map((issue) => (
              <List.Item key={issue}>{issue}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}

      {errors.length > 0 ? (
        <Alert color='red' title='Could not save'>
          <List size='sm'>
            {errors.map((message) => (
              <List.Item key={message}>{message}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}

      <Card withBorder padding='md'>
        <Group justify='space-between' mb='md'>
          <Title order={5}>Classification</Title>
          {data.classification_code ? (
            <Badge size='lg' variant='filled'>
              {data.classification_code}
            </Badge>
          ) : null}
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label='Hazard division'
            placeholder='Not set'
            clearable
            allowDeselect={false}
            data={data.divisions ?? []}
            value={form.division || null}
            onChange={set('division')}
          />
          <Select
            label='Compatibility group'
            placeholder='Not set'
            clearable
            allowDeselect={false}
            data={data.compatibility_groups ?? []}
            value={form.compatibility_group || null}
            onChange={set('compatibility_group')}
          />
          <TextInput
            label='UN number'
            placeholder='e.g. UN0241'
            value={form.un_number}
            onChange={(e) => set('un_number')(e.currentTarget.value)}
          />
          <TextInput
            label='Proper shipping name'
            value={form.proper_shipping_name}
            onChange={(e) => set('proper_shipping_name')(e.currentTarget.value)}
          />
        </SimpleGrid>
      </Card>

      <Card withBorder padding='md'>
        <Title order={5} mb='md'>
          Mass (per unit)
        </Title>

        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <TextInput
            label='Net explosive quantity'
            description='Accepts a unit, e.g. "500 g"'
            placeholder='e.g. 0.5 kg'
            value={form.neq}
            onChange={(e) => set('neq')(e.currentTarget.value)}
          />
          <TextInput
            label='Gross mass'
            placeholder='e.g. 1.2 kg'
            value={form.gross}
            onChange={(e) => set('gross')(e.currentTarget.value)}
          />
          <Stack gap={2}>
            <Text size='sm' fw={500}>
              Packaging / inert mass
            </Text>
            <Text fw={600} mt={6}>
              {data.gross_mass_per_unit_kg !== null &&
              data.neq_per_unit_kg !== null
                ? kg(data.gross_mass_per_unit_kg - data.neq_per_unit_kg)
                : '—'}
            </Text>
          </Stack>
        </SimpleGrid>

        <Text size='xs' c='dimmed' mt='sm'>
          Magazine totals are computed as stock quantity × net explosive
          quantity per unit.
        </Text>
      </Card>

      <Group justify='space-between'>
        <Button onClick={save} loading={saving}>
          Save
        </Button>
        <Button
          variant='subtle'
          color='gray'
          onClick={unmark}
          disabled={saving}
        >
          Not an explosive
        </Button>
      </Group>
    </Stack>
  );
}

/** Shown for a part not yet flagged explosive: the affordance to flag it. */
function MarkExplosive({
  context,
  partId
}: {
  context: InvenTreePluginContext;
  partId: number | string;
}) {
  const [working, setWorking] = useState(false);

  const mark = async () => {
    setWorking(true);
    try {
      await patchPart(context, partId, { is_explosive: true });
      await context.queryClient.invalidateQueries({
        queryKey: ['explosives-part', partId]
      });
    } catch (_error) {
      notifications.show({
        title: 'Could not update',
        message: 'Marking the part as explosive failed. Are you an admin?',
        color: 'red'
      });
    } finally {
      setWorking(false);
    }
  };

  return (
    <Stack gap='md'>
      <Alert color='blue' title='Not an explosive'>
        This part is not flagged as a regulated explosive, so it is not counted
        toward any magazine total. Mark it as explosive to record its net
        explosive quantity and UN classification.
      </Alert>
      <Group>
        <Button onClick={mark} loading={working}>
          Mark as explosive
        </Button>
      </Group>
    </Stack>
  );
}

function PartPanel({ context }: { context: InvenTreePluginContext }) {
  const partId = context.id;

  const query = useQuery(
    {
      queryKey: ['explosives-part', partId],
      queryFn: () => fetchJson<PartExplosive>(context, urls.part(partId!)),
      enabled: !!partId
    },
    context.queryClient
  );

  if (query.isLoading) {
    return (
      <Group>
        <Loader size='sm' />
        <Text>Loading explosive data…</Text>
      </Group>
    );
  }

  const data = query.data;

  if (query.isError || !data) {
    return (
      <Alert color='red' title='Could not load explosives data'>
        The plugin API did not respond. Check that the <b>Enable plugin URLs</b>{' '}
        (ENABLE_PLUGINS_URL) global setting is switched on.
      </Alert>
    );
  }

  if (!data.is_explosive) {
    return <MarkExplosive context={context} partId={partId!} />;
  }

  return <EditForm context={context} partId={partId!} data={data} />;
}

export function RenderPartPanel(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return <PartPanel context={context} />;
}
