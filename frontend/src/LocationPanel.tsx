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
  RingProgress,
  SimpleGrid,
  Stack,
  Table,
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
  type LocationNEQ,
  patchLocationLimit,
  urls,
  utilisationColor
} from './api';

/** A mass value in kg rendered as a string for a text input. */
function massInput(value: number | null): string {
  return value === null || value === undefined ? '' : String(value);
}

/** Editor for a location's licensed limit (staff only; blank removes it). */
function LimitEditor({
  context,
  locationId,
  data
}: {
  context: InvenTreePluginContext;
  locationId: number | string;
  data: LocationNEQ;
}) {
  const [value, setValue] = useState<string>(() => massInput(data.limit_kg));
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // Keyed on the limit itself, not on the query object: a refetch that returns
  // the same limit must not discard a half-typed one.
  const serverLimit = massInput(data.limit_kg);

  useEffect(() => {
    setValue(serverLimit);
    setErrors([]);
  }, [serverLimit]);

  const submit = async (limit: string) => {
    setSaving(true);
    setErrors([]);

    try {
      await patchLocationLimit(context, locationId, { limit_kg: limit });
      await Promise.all([
        context.queryClient.invalidateQueries({
          queryKey: ['explosives-location-neq', locationId]
        }),
        context.queryClient.invalidateQueries({
          queryKey: ['explosives-magazines']
        })
      ]);
      notifications.show({
        title: 'Saved',
        message: limit.trim()
          ? 'Licensed limit updated.'
          : 'Licence removed; this location is no longer tracked.',
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

  return (
    <Stack gap='xs' mt='sm'>
      {errors.length > 0 ? (
        <Alert color='red' title='Could not save'>
          <List size='sm'>
            {errors.map((message) => (
              <List.Item key={message}>{message}</List.Item>
            ))}
          </List>
        </Alert>
      ) : null}
      <Group align='flex-end' gap='xs'>
        <TextInput
          label='Licensed limit'
          description='Accepts a unit, e.g. "50 kg". 0 means no explosives permitted.'
          placeholder='e.g. 50 kg'
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Button onClick={() => submit(value.trim())} loading={saving}>
          Save
        </Button>
        {data.limit_kg !== null ? (
          <Button
            variant='subtle'
            color='gray'
            onClick={() => submit('')}
            disabled={saving}
          >
            Remove licence
          </Button>
        ) : null}
      </Group>
    </Stack>
  );
}

/** NEQ panel for a StockLocation. Shown on every location so a licence can be set. */
function LocationPanel({ context }: { context: InvenTreePluginContext }) {
  const locationId = context.id;

  const query = useQuery(
    {
      queryKey: ['explosives-location-neq', locationId],
      queryFn: () =>
        fetchJson<LocationNEQ>(context, urls.locationNEQ(locationId!)),
      enabled: !!locationId
    },
    context.queryClient
  );

  if (query.isLoading) {
    return (
      <Group>
        <Loader size='sm' />
        <Text>Calculating net explosive quantity…</Text>
      </Group>
    );
  }

  const data = query.data;

  if (query.isError || !data) {
    return (
      <Alert color='red' title='Could not load explosives data'>
        <Stack gap='xs'>
          <Text>The plugin API did not respond.</Text>
          <Text size='sm' c='dimmed'>
            Check that the <b>Enable plugin URLs</b> (ENABLE_PLUGINS_URL) global
            setting is switched on.
          </Text>
        </Stack>
      </Alert>
    );
  }

  const licensed = data.limit_kg !== null; // 0 kg is a licence, null is not
  const color = utilisationColor(data.utilisation, data.over_limit);
  const percent = data.over_limit
    ? 100
    : Math.min(100, (data.utilisation ?? 0) * 100);
  const canEdit = context.user?.isStaff?.() ?? false;

  return (
    <Stack gap='md'>
      {data.config_errors?.length ? (
        <Alert color='orange' title='Plugin configuration problem'>
          <Stack gap='xs'>
            {data.config_errors.map((error) => (
              <Text key={error} size='sm'>
                {error}
              </Text>
            ))}
          </Stack>
        </Alert>
      ) : null}

      {data.over_limit && licensed ? (
        <Alert color='red' title='Licensed net explosive quantity exceeded'>
          This location holds <b>{kg(data.neq_kg)}</b> against a licensed limit
          of <b>{kg(data.limit_kg)}</b> — an excess of{' '}
          <b>{kg(data.neq_kg - (data.limit_kg ?? 0))}</b>.
        </Alert>
      ) : null}

      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Card withBorder padding='md'>
          <Group>
            <RingProgress
              size={140}
              thickness={14}
              sections={[{ value: percent, color }]}
              label={
                <Stack gap={0} align='center'>
                  <Text fw={700} size='lg'>
                    {data.neq_kg.toFixed(2)}
                  </Text>
                  <Text size='xs' c='dimmed'>
                    kg NEQ
                  </Text>
                </Stack>
              }
            />
            <Stack gap={4}>
              <Text size='sm' c='dimmed'>
                Licensed limit
              </Text>
              <Text fw={600}>
                {licensed ? kg(data.limit_kg) : 'Not licensed'}
              </Text>

              {licensed ? (
                <>
                  <Text size='sm' c='dimmed' mt='xs'>
                    Utilisation
                  </Text>
                  <Badge color={color} variant='light'>
                    {data.utilisation !== null
                      ? `${(data.utilisation * 100).toFixed(1)}%`
                      : data.over_limit
                        ? 'Nothing permitted'
                        : 'Empty'}
                  </Badge>
                </>
              ) : (
                <Text size='xs' c='dimmed' maw={220}>
                  {canEdit
                    ? 'Set a licensed limit below to track this location against a licence.'
                    : 'Ask an administrator to set a licensed limit to track this location against a licence.'}
                </Text>
              )}

              <Text size='sm' c='dimmed' mt='xs'>
                Gross mass
              </Text>
              <Text>{kg(data.gross_mass_kg)}</Text>
            </Stack>
          </Group>

          {data.include_sublocations ? (
            <Text size='xs' c='dimmed' mt='sm'>
              Includes stock held in sublocations.
            </Text>
          ) : null}

          {canEdit ? (
            <LimitEditor
              context={context}
              locationId={locationId!}
              data={data}
            />
          ) : null}
        </Card>

        <Card withBorder padding='md'>
          <Title order={5} mb='sm'>
            By hazard division
          </Title>

          {Object.keys(data.by_division).length === 0 ? (
            <Text c='dimmed' size='sm'>
              No explosive stock in this location.
            </Text>
          ) : (
            <Table>
              <Table.Tbody>
                {Object.entries(data.by_division).map(([division, mass]) => (
                  <Table.Tr key={division}>
                    <Table.Td>
                      <Badge variant='light'>{division}</Badge>
                    </Table.Td>
                    <Table.Td ta='right'>{kg(mass)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Card>
      </SimpleGrid>

      <Card withBorder padding='md'>
        <Title order={5} mb='sm'>
          Contributing stock
        </Title>

        {data.items.length === 0 ? (
          <Text c='dimmed' size='sm'>
            No explosive stock in this location.
          </Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Part</Table.Th>
                <Table.Th>Location</Table.Th>
                <Table.Th>Class</Table.Th>
                <Table.Th>UN</Table.Th>
                <Table.Th ta='right'>Qty</Table.Th>
                <Table.Th ta='right'>NEQ / unit</Table.Th>
                <Table.Th ta='right'>NEQ total</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.items.map((item) => (
                <Table.Tr key={item.stock_item_id}>
                  <Table.Td>
                    <Text
                      size='sm'
                      style={{ cursor: 'pointer' }}
                      onClick={() =>
                        context.navigate(`/stock/item/${item.stock_item_id}/`)
                      }
                    >
                      {item.part_name}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size='sm' c='dimmed'>
                      {item.location_name ?? '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {item.classification_code ? (
                      <Badge variant='light'>{item.classification_code}</Badge>
                    ) : (
                      <Text c='dimmed' size='sm'>
                        —
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>{item.un_number ?? '—'}</Table.Td>
                  <Table.Td ta='right'>{item.quantity}</Table.Td>
                  <Table.Td ta='right'>{kg(item.neq_per_unit_kg)}</Table.Td>
                  <Table.Td ta='right'>
                    <Text fw={600}>{kg(item.neq_total_kg)}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
            <Table.Tfoot>
              <Table.Tr>
                <Table.Th colSpan={6} ta='right'>
                  Total
                </Table.Th>
                <Table.Th ta='right'>{kg(data.neq_kg)}</Table.Th>
              </Table.Tr>
            </Table.Tfoot>
          </Table>
        )}
      </Card>
    </Stack>
  );
}

export function RenderLocationPanel(context: InvenTreePluginContext) {
  checkPluginVersion(context);

  return <LocationPanel context={context} />;
}
