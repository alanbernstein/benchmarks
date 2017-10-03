# -*- coding: utf-8 -*-
from collections import defaultdict
import os
import configparser
from flask import Flask, render_template, jsonify, request
import psycopg2
#.from flask_sqlalchemy import SQLAlchemy
#from sqlalchemy import column
#from sqlalchemy.sql import func

MICROSEC_TO_SEC = 0.000001

####################################################
# config

Config = configparser.ConfigParser()
Config.read("pilosa.cfg")

section = "App"
if section not in Config.sections():
    host = "127.0.0.1"
    port = 5000
else:
    host = Config.get(section, 'host')
    port = int(Config.get(section, 'port'))

section = "Postgres"
if section not in Config.sections():
    raise Exception
else:
    db_conn = "dbname='%s'" % Config.get(section, 'database')
    db_args = (Config.get(section, 'username'),
               Config.get(section, 'password'),
               Config.get(section, 'hostname'),
               Config.get(section, 'database'))
    db_url = 'postgresql://%s:%s@%s/%s' % db_args

section = "S3"
if section not in Config.sections():
    raise Exception
else:
    bucket_name = Config.get("S3", "bucket")

sync_base_path = os.path.expanduser(Config.get("S3", 'sync_base_path'))
sync_path = sync_base_path + '/' + bucket_name

if not os.path.exists(sync_base_path):
    os.mkdir(sync_path)
if not os.path.exists(sync_path):
    os.mkdir(sync_path)

####################################################
# init

color_cycle = {
    'pilosa-blue': '#3C5F8D',
    'pilosa-light-blue': '#CFEAEC',
    'pilosa-green': '#1DB598',
    'pilosa-red': '#FF2B2B',
    'pilosa-dark-blue': '#102445',
    'orange': '#FFA500',
    'magenta': '#FF00FF',
    'lime': '#00FF00',
    'cyan': '#00FFFF',
    'yellow': '#FFFF00',
}


app = Flask(__name__)
#app.config['SQLALCHEMY_DATABASE_URI'] = db_url
#app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
#db = SQLAlchemy(app)

conn = psycopg2.connect(db_conn)
cur = conn.cursor()

####################################################
# models

# class Run(db.Model):
# class Benchmark(db.Model):

####################################################
# endpoints

@app.route('/sync')
def sync():
    m = []
    # new, skipped = sync_s3_bucket(bucket_name, sync_path, postgres_import, 'json')
    # m = 'imported benchmark json files from S3: %d new, %d skipped<br>\n' % (new, skipped)
    # data = read_all_local(sync_path, 'json')
    # runs, results = collate(data)
    # insert_data(runs, results)
    # print(m)
    return '<br />\n'.join(m)


READ_RESULTS = 'SELECT name, config_index, stats_mean_us, pilosa_version, run_id FROM benchmarks'
READ_RUN_BY_ID = "SELECT uuid, pi_version, spawn_file FROM runs WHERE id='%d'"
READ_RESULT_RUNS = "SELECT runs.id, runs.uuid, runs.pi_version, runs.pi_build_time, runs.spawn_file, benchmarks.run_id, benchmarks.name, benchmarks.config_index, benchmarks.stats_mean_us, benchmarks.pilosa_version FROM runs, benchmarks WHERE runs.id = benchmarks.run_id"


def get_filtered_benchmark_rows(filter_fields):
    labels = ['Name', 'Index', 'mean (s)', 'Pilosa version', 'Spawn name']
    psql_select = READ_RESULTS
    psql_where = []
    for k, v in filter_fields.items():
        print(k, v)
        if k in ['name', 'config_index', 'pilosa_version']:
            psql_where.append("%s LIKE '%%%s%%'" % (k, v))

    psql = '%s WHERE %s' % (psql_select, ' AND '.join(psql_where))

    try:
        cur.execute(psql)
        conn.commit()
    except Exception as exc:
        print(exc)
        conn.rollback()
        import ipdb; ipdb.set_trace()
    row_tuples = cur.fetchall()
    return row_tuples, labels


def get_run_by_id(run_id):
    psql = READ_RUN_BY_ID % run_id
    cur.execute(psql)
    conn.commit()
    run = cur.fetchone()
    # print(psql)
    # print(run)
    return run


def get_filtered_benchmarkruns(filter_fields):
    headers = ['run_id', 'uuid', 'pi_version', 'pi_build_time', 'spawn_file', 'run_id', 'name', 'config_index', 'stats_mean_us', 'pilosa_version']
    psql_select = READ_RESULT_RUNS
    psql_where = []

    for k, v in filter_fields.items():
        print(k, v)
        if k in ['name', 'config_index', 'pilosa_version', 'pi_version', 'spawn_file']:
            psql_where.append("%s LIKE '%%%s%%'" % (k, v))

    psql_parts = [psql_select]
    psql_parts += psql_where
    psql = ' AND '.join(psql_parts)

    # TODO: groupby the group_field

    print(psql)
    try:
        cur.execute(psql)
        conn.commit()
    except Exception as exc:
        print(exc)
        conn.rollback()
        import ipdb; ipdb.set_trace()
    row_tuples = cur.fetchall()
    return row_tuples, headers


def parse_args(args):
    filter_fields = {k: v for k, v in args.items() if k != 'group'}
    group_field = args.get('group', None)
    return filter_fields, group_field


@app.route('/compare')
def compare():
    title = 'Pilosa benchmark comparison'
    filter_fields, group_field = parse_args(request.args)

    #row_tuples, labels = get_filtered_benchmark_rows(filter_fields)
    #rows = []
    #for row in row_tuples:
    #    row_list = list(row)[0:4]
    #    row_list[2] *= MICROSEC_TO_SEC
    #    run = get_run_by_id(row[4])
    #    row_list.append(run[2])
    #    rows.append(row_list)

    row_tuples, headers = get_filtered_benchmarkruns(filter_fields)
    rows = []
    for row in row_tuples:
        row_list = list(row)
        row_list[8] *= MICROSEC_TO_SEC
        rows.append(row_list)

    return render_template(
        'compare.html',
        title=title,
        rowcount=len(rows),
        headers=headers,
        rows=rows,
    )


# @app.route('/graph/group/<string:group>')
@app.route('/simplegraph')
def simplegraph():
    title = 'Pilosa benchmark graph'
    filter_fields, group_field = parse_args(request.args)

    row_tuples, headers = get_filtered_benchmarkruns(filter_fields)
    row_tuples.sort(key=lambda x: x[3])
    # TODO: group by the group_field, creating separate datasets for each group
    xyt = []
    for row in row_tuples:
        if row[8] <= 0:
            continue
        xyt.append((
            row[3].strftime('%Y/%m/%d %H:%M:%S'),
            row[8]*MICROSEC_TO_SEC,
            '%s %s %s %s' % (row[4], row[6], row[7], row[9]),
            # spawn-config, name, index, pilosa-version
        ))

    plot_data = [
        {
            'label': 'All benchmarks',
            'xyt': xyt,
            'color': color_cycle.values()[0],
        },
    ]
    return render_template('linegraph.html',
                           plot_data=plot_data,
                           title=title,
                           xlabel='Date',
                           ylabel='Benchmark time (seconds)',
    )


@app.route('/timegraph')
def timegraph():
    keys = ['run_id', 'run_uuid', 'pi_version', 'pi_build_time', 'spawn', 'brun_id', 'name', 'config_index', 'mean', 'version']

    title = 'Benchmark time series'
    filter_fields, group_field = parse_args(request.args)

    # get all results
    row_tuples, headers = get_filtered_benchmarkruns(filter_fields)

    # sort by time
    row_tuples.sort(key=lambda x: x[3])

    # group and transform xy values
    xyt_dict = defaultdict(list)
    for row in row_tuples:
        key = 'All benchmarks'
        if group_field:
            key = row[keys.index(group_field)]

        if row[8] <= 0:
            continue
        xyt_dict[key].append((
            row[3].strftime('%Y/%m/%d %H:%M:%S'),
            row[8]*MICROSEC_TO_SEC,
            '%s %s %s %s' % (row[4], row[6], row[7], row[9]),
            # spawn-config, name, index, pilosa-version
        ))

    # package up for Chart.js
    plot_data = []
    n = 0
    keys = xyt_dict.keys()
    keys.sort()
    for key in keys:
        plot_data.append({
            'label': key,
            'xyt': xyt_dict[key],
            'color': color_cycle.values()[n],
        })
        n += 1

    return render_template('timegraph.html',
                           plot_data=plot_data,
                           title=title,
                           xlabel='Date',
                           ylabel='Benchmark time (seconds)',
    )


def version_sort_key(vstring):
    parts = vstring.split('-')
    if len(parts) == 1:
        release, = parts
        return (release, 0)
    elif len(parts) == 3:
        release, commit_count, commit_hash = parts
        return (release, int(commit_count))


@app.route('/versiongraph')
def versiongraph():
    title = 'Version comparison'
    filter_fields, group_field = parse_args(request.args)

    # get all results
    row_tuples, headers = get_filtered_benchmarkruns(filter_fields)
    print(len(row_tuples))

    # sort by version
    labels = list(set([r[9] for r in row_tuples]))
    labels.sort(key=version_sort_key)

    # group xy values
    plot_data = []
    for row in row_tuples:
        plot_data.append((
            labels.index(row[9]),
            row[8]*MICROSEC_TO_SEC,
            '%s %s %s %s' % (row[3], row[4], row[6], row[7]),
        ))

    print(len(plot_data))
    return render_template('versiongraph.html',
                           labels=labels,
                           plot_data=plot_data,
                           title=title,
                           xlabel='Pilosa version',
                           ylabel='Benchmark time (seconds)',
    )


@app.route('/')
def index():
    return render_template('index.html')


####################################################
# start
app.run(host=host, port=port, debug=1)
