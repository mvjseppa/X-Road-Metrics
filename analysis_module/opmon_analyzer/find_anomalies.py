#
# 2018-01-15 by Toomas Mölder
# Some temporary logging (activity includes _tmp_ added for all steps to better understand, what steps take how long and what indexes to create
# TODO: add exception handling
#
from .AnalyzerDatabaseManager import AnalyzerDatabaseManager
from .models.FailedRequestRatioModel import FailedRequestRatioModel
from .models.DuplicateMessageIdModel import DuplicateMessageIdModel
from .models.TimeSyncModel import TimeSyncModel
from .models.AveragesByTimeperiodModel import AveragesByTimeperiodModel
from . import analyzer_conf
from .logger_manager import LoggerManager


import time
import datetime

import numpy as np


def find_anomalies(settings):
    db_manager = AnalyzerDatabaseManager(settings, analyzer_conf)
    logger_m = LoggerManager(settings['logger'], settings['xroad']['instance'])

    logger_m.log_info('_tmp_find_anomalies_start', "Process started ...")

    current_time = datetime.datetime.now()

    # add first request timestamps for service calls that have appeared
    logger_m.log_info('_tmp_find_anomalies_1', "Add first request timestamps for service calls that have appeared ...")
    logger_m.log_heartbeat("Checking if completely new service calls have appeared", 'SUCCEEDED')

    db_manager.add_first_request_timestamps_from_clean_data()

    logger_m.log_info('_tmp_find_anomalies_1',
                      "Add first request timestamps for service calls that have appeared ... Done!")

    logger_m.log_info('_tmp_find_anomalies_2', "Anomaly types 4.3.1-4.3.3 ...")
    for model_type, time_window in analyzer_conf.time_windows.items():
        logger_m.log_info('_tmp_find_anomalies_2', f"Finding {model_type} anomalies, aggregating by {time_window}...")
        logger_m.log_heartbeat(f"Finding {model_type} anomalies, aggregating by {time_window}", 'SUCCEEDED')

        start = time.time()
        last_transform_date = db_manager.get_timestamp(ts_type="last_transform_timestamp", model_type=model_type)
        if last_transform_date is not None:
            last_transform_timestamp = last_transform_date.timestamp() * 1000
        else:
            last_transform_timestamp = None
        current_transform_date = current_time - datetime.timedelta(minutes=analyzer_conf.corrector_buffer_time)

        residual = current_transform_date.timestamp() % (60 * time_window["agg_minutes"])
        current_transform_timestamp = (current_transform_date.timestamp() - residual) * 1000

        if model_type == "failed_request_ratio":
            model = FailedRequestRatioModel(analyzer_conf)
            data = db_manager.aggregate_data(model_type=model_type,
                                             start_time=last_transform_timestamp,
                                             end_time=current_transform_timestamp,
                                             agg_minutes=time_window["agg_minutes"])
            anomalies = model.transform(data, time_window)
            if len(anomalies) > 0:
                db_manager.insert_incidents(anomalies)
            n_anomalies = len(anomalies)

        elif model_type == "duplicate_message_ids":
            model = DuplicateMessageIdModel(analyzer_conf)
            data = db_manager.aggregate_data(model_type=model_type,
                                             start_time=last_transform_timestamp,
                                             end_time=current_transform_timestamp,
                                             agg_minutes=time_window["agg_minutes"])
            anomalies = model.transform(data, time_window)
            if len(anomalies) > 0:
                db_manager.insert_incidents(anomalies)
            n_anomalies = len(anomalies)

        elif model_type == "time_sync_errors":
            model = TimeSyncModel(analyzer_conf)
            n_anomalies = 0
            for metric, threshold in analyzer_conf.time_sync_monitored_lower_thresholds.items():
                start = time.time()
                data = db_manager.aggregate_data(model_type=model_type,
                                                 start_time=last_transform_timestamp,
                                                 end_time=current_transform_timestamp,
                                                 agg_minutes=time_window["agg_minutes"],
                                                 metric=metric,
                                                 threshold=threshold)
                anomalies = model.transform(data, metric, threshold, time_window)
                if len(anomalies) > 0:
                    db_manager.insert_incidents(anomalies)
                n_anomalies += len(anomalies)

        t0 = np.round(time.time() - start, 2)
        logger_m.log_info('find_anomalies', f"{model_type} anomalies time: {t0} seconds.")

        if last_transform_date is not None:
            logger_m.log_info('find_anomalies',
                              f"Used data between {last_transform_date} and {current_transform_date}.")
        else:
            logger_m.log_info('find_anomalies', f"Used data until {current_transform_date}")
        logger_m.log_info('find_anomalies', f"Found {n_anomalies} anomalies.")

        db_manager.set_timestamp(ts_type="last_transform_timestamp",
                                 model_type=model_type,
                                 value=datetime.datetime.fromtimestamp(current_transform_timestamp / 1000.0))

    logger_m.log_info('_tmp_find_anomalies_2', "Anomaly types 4.3.1-4.3.3 ... Done!")

    logger_m.log_info('_tmp_find_anomalies_3', "Anomaly types 4.3.5 - 4.3.9. Comparison with historic averages ...")
    logger_m.log_heartbeat("Determining service call stages", 'SUCCEEDED')
    sc_regular, sc_first_incidents = db_manager.get_service_calls_for_transform_stages()
    logger_m.log_info(
        'find_anomalies',
        f"No. service calls that have passed the training period for the first time: {len(sc_first_incidents)}"
    )

    logger_m.log_info('find_anomalies', f"Number of service calls in regular mode: {len(sc_regular)}")

    for time_window, _ in analyzer_conf.historic_averages_time_windows:
        last_transform_date = db_manager.get_timestamp(ts_type="last_transform_timestamp",
                                                       model_type=time_window['timeunit_name'])
        logger_m.log_info('_tmp_find_anomalies_3', f"Model type: {time_window['timeunit_name']}")

        if last_transform_date is not None:
            last_transform_timestamp = last_transform_date.timestamp() * 1000
        else:
            last_transform_timestamp = None
        current_transform_date = current_time - datetime.timedelta(minutes=analyzer_conf.corrector_buffer_time)

        residual = current_transform_date.timestamp() % (60 * time_window["agg_window"]["agg_minutes"])
        current_transform_timestamp = (current_transform_date.timestamp() - residual) * 1000

        start = time.time()
        logger_m.log_info('_tmp_find_anomalies_3',
                          f"Reading data and aggregating (model {time_window['timeunit_name']})")

        logger_m.log_heartbeat("Reading data and aggregating (model {time_window['timeunit_name']})", 'SUCCEEDED')

        data = db_manager.get_data_for_transform_stages(
            time_window["agg_window"]["agg_minutes"],
            last_transform_timestamp,
            current_transform_timestamp,
            sc_regular,
            sc_first_incidents
        )

        if len(data) > 0:
            logger_m.log_info('_tmp_find_anomalies_3', "Loading the %s model" % time_window['timeunit_name'])
            logger_m.log_heartbeat("Loading the %s model" % time_window['timeunit_name'], 'SUCCEEDED')
            dt_model = db_manager.load_model(model_name=time_window['timeunit_name'], version=None)
            dt_model = dt_model.groupby(analyzer_conf.service_call_fields + ["similar_periods"]).first()
            averages_by_time_period_model = AveragesByTimeperiodModel(time_window, analyzer_conf, dt_model)

            logger_m.log_info('_tmp_find_anomalies_3', "Finding anomalies (model %s)" % time_window['timeunit_name'])
            logger_m.log_heartbeat("Finding anomalies (model %s)" % time_window['timeunit_name'], 'SUCCEEDED')
            anomalies = averages_by_time_period_model.transform(data)

            t0 = np.round(time.time() - start, 2)
            logger_m.log_info(
                'find_anomalies',
                f"Averages by timeperiod ({time_window['timeunit_name']}) anomaly finding time: {t0} seconds."
            )

            logger_m.log_info('find_anomalies',
                              f"Used data between {last_transform_date} and {current_transform_date}.")
            logger_m.log_info('find_anomalies', f"Found {len(anomalies)} anomalies.")

            if len(anomalies) > 0:
                db_manager.insert_incidents(anomalies)

        logger_m.log_info('_tmp_find_anomalies_3',
                          f"Updating last anomaly finding timestamp (model {time_window['timeunit_name']})")
        logger_m.log_heartbeat(f"Updating last anomaly finding timestamp (model {time_window['timeunit_name']})",
                               'SUCCEEDED')

        db_manager.set_timestamp(ts_type="last_transform_timestamp", model_type=time_window['timeunit_name'],
                                 value=datetime.datetime.fromtimestamp(current_transform_timestamp / 1000.0))

    logger_m.log_info('_tmp_find_anomalies_3',
                      "Anomaly types 4.3.5 - 4.3.9. Comparison with historic averages ... Done!")
    logger_m.log_info('_tmp_find_anomalies_4', "Incident timestamps ...")

    if len(sc_first_incidents) > 0:
        logger_m.log_heartbeat("Updating first incident timestamps", 'SUCCEEDED')
        db_manager.update_first_timestamps(field="first_incident_timestamp",
                                           value=current_time,
                                           service_calls=sc_first_incidents[analyzer_conf.service_call_fields])
    logger_m.log_info('_tmp_find_anomalies_4', "Incident timestamps ... Done!")

    logger_m.log_info('_tmp_find_anomalies_end',
                      "Process finished ... Done!")