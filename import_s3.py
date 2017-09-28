import glob
import json
import os

import boto3
import configparser
import psycopg2

Config = configparser.ConfigParser()
Config.read("pilosa.cfg")
bucket_name = Config.get("S3", "bucket")
db_name = Config.get("Postgres", "database")
sync_base_path = os.path.expanduser(Config.get("S3", 'sync_base_path'))
sync_path = sync_base_path + '/' + bucket_name

if not os.path.exists(sync_base_path):
    os.mkdir(sync_path)
if not os.path.exists(sync_path):
    os.mkdir(sync_path)


"""
create table runs (id int primary key, uuid uuid, pi_version varchar(32), pi_build_time timestamp, config json, spawn_file varchar(256));
create table benchmarks (id int primary key, run_id int references runs (id), name varchar(256), config json, config_index varchar(64), stats json, stats_total_us bigint, stats_min_us bigint, stats_max_us bigint, stats_num bigint, stats_mean_us bigint, extra json, agentnum int, error varchar(256), duration_us bigint, pilosa_version varchar(32));
"""

conn = psycopg2.connect("dbname='%s'" % db_name)
cur = conn.cursor()
INSERT_RUN = """INSERT INTO runs (id, uuid, pi_version, pi_build_time, config, spawn_file) VALUES ('%s', '%s', '%s', '%s', '%s', '%s')"""
INSERT_RESULT = """INSERT INTO benchmarks (id, run_id, name, config, config_index, stats, stats_total_us, stats_min_us, stats_max_us, stats_num, stats_mean_us, extra, agentnum, error, duration_us, pilosa_version) VALUES ('%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s')"""

class BenchmarkRun(object):
    def __init__(self, **kwargs):
        [setattr(self, k, v) for k, v in kwargs.iteritems()]

    def __repr__(self):
        return '<run %s %s %s %s>' % (self.uuid, self.pi_version, self.pi_build_time, self.spawn_file)


class BenchmarkResult(object):
    def __init__(self, **kwargs):
        [setattr(self, k, v) for k, v in kwargs.iteritems()]

    def __repr__(self):
        return '<result %s %s %s>' % (self.name, self.stats_mean_us, self.pilosa_version)


def main():
    sync_s3_bucket(bucket_name, sync_path, postgres_import, 'json')
    data = read_all_local(sync_path, 'json')
    runs, results = collate(data)
    insert_data(runs, results)

    # print_all(data)
    # print(json.dumps(data.values()[0], indent=2))
    import ipdb; ipdb.set_trace()


def insert_data(runs, results):
    print('inserting %d runs and %d results into local db' % (len(runs), len(results)))
    for n, run in enumerate(runs):
        print('run %d' % n)
        values = (
            run.id,
            run.uuid,
            run.pi_version,
            run.pi_build_time,
            json.dumps(run.configuration).replace("'", ""),
            run.spawn_file,
        )
        psql = INSERT_RUN % values

        try:
            cur.execute(psql)
            conn.commit()
        except Exception as exc:
            print(exc)
            conn.rollback()
            import ipdb; ipdb.set_trace()

    for n, result in enumerate(results):
        print('result %d' % n)
        if result.error:
            print('%d: skipping error' % n)
            print(result.error)
            continue
        values = (
            result.id,
            result.run_id,
            result.name,
            json.dumps(result.configuration),
            result.configuration_index,
            json.dumps(result.stats),
            result.stats_total_us,
            result.stats_min_us,
            result.stats_max_us,
            result.stats_num,
            result.stats_mean_us,
            json.dumps(result.extra),
            result.agentnum,
            result.error,
            result.duration,
            result.pilosa_version,
        )
        psql = INSERT_RESULT % values
        print(psql)
        try:
            cur.execute(psql)
            conn.commit()
        except Exception as exc:
            print(exc)
            conn.rollback()
            import ipdb; ipdb.set_trace()

def collate(data):
    print('collating data from %d files' % len(data))
    wrong_format = []
    runs = []
    results = []
    run_id = 0
    result_id = 0
    for k, d in data.items():
        if k == 'ff178f44-8769-11e7-9837-60f81dc0b346.json':
            import ipdb; ipdb.set_trace()
        if 'configuration' not in d:
            print('%s: no configuration included' % k)
            wrong_format.append(k)
            continue

        brun = BenchmarkRun(
            id=run_id,
            uuid=d['run-uuid'],
            pi_version=d['pi-version'],
            pi_build_time=d['pi-build-time'],
            configuration=d['configuration'],
            spawn_file=d['configuration']['spawn-file'],
            filename=k,
        )
        runs.append(brun)

        for res in d['benchmark-results']:
            # TODO only looking at first agent-results here
            ar0 = res['agent-results'][0]
            if 'stats' not in ar0 or ar0['stats'] is None:
                print('  %s: no stats included' % k)
                continue
            stats = ar0['stats']
            bres = BenchmarkResult(
                id=result_id,
                run_id=run_id,
                name=res['benchmark-name'],
                configuration=ar0['configuration'],
                stats=stats,
                stats_total_us=stats['total-time'],
                stats_min_us=stats['min'],
                stats_max_us=stats['max'],
                stats_num=stats['num'],
                stats_mean_us=stats['mean'],
                extra=ar0['extra'],
                agentnum=ar0['agentnum'],
                error=ar0['error'],
                duration=ar0['duration'],
                pilosa_version=ar0['pilosa-version'],
            )
            if 'index' in ar0['configuration']:
                bres.configuration_index = ar0['configuration']['index']
            else:
                bres.configuration_index = ''

            results.append(bres)
            result_id += 1
        run_id += 1

    return runs, results


def print_all(data):
    print('%5s %5s %5s %36s %7s %24s' % ('n', 'conf', 'res', 'uuid', 'version', 'build-time'))
    for n, (k, d) in enumerate(data.items()):
        if k in wrong_format:
            continue

        conf = d.get('configuration', [])
        res = d.get('benchmark-results', [])
        print('%5d %5d %5d %s %s %s' % (n, len(conf), len(res), d['run-uuid'], d['pi-version'], d['pi-build-time']))

    print('\nwrong format:')
    for k in wrong_format:
        print(k)

    # print(json.dumps(data.values()[0]['configuration'], indent=2))
    # print(data.values()[0]['benchmark-results'])


def read_all_local(path, ext, debugprint=False):
    data = {}
    files = glob.glob('%s/*.%s' % (path, ext))
    for file in files:
        with open(file) as f:
            data[file] = json.load(f)
        if not debugprint:
            continue

        print(file)
        for k, v in data[file].items():
            if k == 'pi-version':
                print('  pi-version: %s' % data[file]['pi-version'])
            elif k == 'pi-build-time':
                print('  pi-build-time: %s' % data[file]['pi-build-time'])
            elif k == 'run-uuid':
                print('  run-uuid: %s' % data[file]['run-uuid'])
            elif k == 'configuration': 
                print('  config: %s' % (data[file]['configuration'].keys()))
            elif k == 'benchmark-results':
                br = data[file]['benchmark-results']
                print('  results: %d' % len(br))
                for brn in br:
                    print('    %s: %d' % (brn['benchmark-name'], len(brn['agent-results'])))
            else:
                print('  %s: %s' % (k, type(v)))

    return data


def postgres_import(key, content):
    pass


def sync_s3_bucket(bucket_name, base_path, handler, ext=None):
    skipped = 0
    downloaded = 0
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)
    for obj in bucket.objects.all():
        if ext not in obj.key:
            continue
        path = base_path + '/' + obj.key

        if not os.path.exists(path):
            bucket.download_file(obj.key, path)
            downloaded += 1
            handler(obj.key, '')
            print(obj.key)
        else:
            skipped += 1

    print('saved %d files from s3, skipped %d' % (downloaded, skipped))


main()
