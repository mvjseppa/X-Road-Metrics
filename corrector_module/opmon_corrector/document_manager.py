""" Document Manager - Corrector Module
"""

import collections
import hashlib

from .logger_manager import LoggerManager


class DocumentManager:
    def __init__(self, settings):

        self.calc = settings['corrector']['calc']
        self.logger_m = LoggerManager(settings['logger'], settings['xroad']['instance'])
        self.TIME_WINDOW = settings['corrector']['time-window']
        self.COMPARISON_LIST = settings['corrector']['comparison-list']
        self.orphan_comparison_list = settings['corrector']['comparison_list_orphan']

        self.must_fields = (
            'monitoringDataTs', 'securityServerInternalIp', 'securityServerType', 'requestInTs', 'requestOutTs',
            'responseInTs', 'responseOutTs', 'clientXRoadInstance', 'clientMemberClass', 'clientMemberCode',
            'clientSubsystemCode', 'serviceXRoadInstance', 'serviceMemberClass', 'serviceMemberCode',
            'serviceSubsystemCode', 'serviceCode', 'serviceVersion', 'representedPartyClass', 'representedPartyCode',
            'messageId', 'messageUserId', 'messageIssue', 'messageProtocolVersion', 'clientSecurityServerAddress',
            'serviceSecurityServerAddress', 'requestSoapSize', 'requestMimeSize', 'requestAttachmentCount',
            'responseSoapSize', 'responseMimeSize', 'responseAttachmentCount', 'succeeded', 'soapFaultCode',
            'soapFaultString'
        )

    @staticmethod
    def subtract_or_none(a, b):
        return None if None in [a, b] else a - b

    def _client_calculations(self, in_doc):
        """
        Calculates client specific parameters.
        :param in_doc: The input document.
        :return: Returns the document with applied calculations.
        """
        client = in_doc.get('client') or {}
        request_in = client.get('requestInTs')
        request_out = client.get('requestOutTs')
        response_in = client.get('responseInTs')
        response_out = client.get('responseOutTs')

        if self.calc['total-duration']:
            in_doc['totalDuration'] = self.subtract_or_none(response_out, request_in)

        if self.calc['client-request-duration']:
            in_doc['clientSsRequestDuration'] = self.subtract_or_none(request_out, request_in)

        if self.calc['client-response-duration']:
            in_doc['clientSsResponseDuration'] = self.subtract_or_none(response_out, response_in)

        if self.calc['producer-duration-client-view']:
            in_doc['producerDurationClientView'] = self.subtract_or_none(response_in, request_out)

        return in_doc

    def _producer_calculations(self, in_doc):
        """
        Calculates producer specific parameters.
        :param in_doc: The input document.
        :return: Returns the document with applied calculations.
        """
        producer = in_doc.get('producer') or {}
        request_in = producer.get('requestInTs')
        request_out = producer.get('requestOutTs')
        response_in = producer.get('responseInTs')
        response_out = producer.get('responseOutTs')

        if self.calc['producer-duration-producer-view']:
            in_doc['producerDurationProducerView'] = self.subtract_or_none(response_out, request_in)

        if self.calc['producer-request-duration']:
            in_doc['producerSsRequestDuration'] = self.subtract_or_none(request_out, request_in)

        if self.calc['producer-response-duration']:
            in_doc['producerSsResponseDuration'] = self.subtract_or_none(response_out, response_in)

        if self.calc['producer-is-duration']:
            in_doc['producerIsDuration'] = self.subtract_or_none(response_in, request_out)

        return in_doc

    def _pair_calculations(self, in_doc):
        """
        Calculates pair specific parameters.
        :param in_doc: The input document.
        :return: Returns the document with applied calculations.
        """

        client = in_doc.get('client') or {}
        producer = in_doc.get('producer') or {}

        producer_request_in = producer.get('requestInTs')
        producer_response_out = producer.get('responseOutTs')
        client_response_in = client.get('responseInTs')
        client_request_out = client.get('requestOutTs')

        if self.calc['request-nw-duration']:
            in_doc['requestNwDuration'] = self.subtract_or_none(producer_request_in, client_request_out)

        if self.calc['response-nw-duration']:
            in_doc['responseNwDuration'] = self.subtract_or_none(client_response_in, producer_response_out)

        if self.calc['request-size']:
            in_doc['clientRequestSize'] = self.calculate_transaction_size(client, 'request')
            in_doc['producerRequestSize'] = self.calculate_transaction_size(producer, 'request')

        if self.calc['response-size']:
            in_doc['clientResponseSize'] = self.calculate_transaction_size(client, 'response')
            in_doc['producerResponseSize'] = self.calculate_transaction_size(producer, 'response')

        return in_doc

    @staticmethod
    def calculate_transaction_size(document_member: dict, transaction_type: str):
        if transaction_type not in ['request', 'response']:
            return None

        size = None

        try:
            if document_member[f'{transaction_type}AttachmentCount'] in [0, None]:
                size = document_member[f'{transaction_type}SoapSize']
            elif document_member[f'{transaction_type}AttachmentCount'] > 0:
                size = document_member[f'{transaction_type}MimeSize']
        except (TypeError, ValueError, KeyError):
            pass

        return size

    @staticmethod
    def get_boundary_value(value):
        """
        Fixes the minimum value at -2 ** 31 + 1 and maximum value at 2 ** 31 - 1.
        :param value: The value to be checked.
        :return: Returns either the input value or the min_value or the max_value based on the input value.
        """
        lo = -2 ** 31 + 1
        hi = 2 ** 31 - 1

        return None if value is None else max(min(value, hi), lo)

    def _limit_calculation_values(self, document):
        """
        Limits all the calculated values to either -2 ** 31 + 1 (min) or 2 ** 31 - 1 (max).
        :param document: The input document.
        :return: Returns the document with fixed values.
        """
        keys_to_limit = [
            'clientSsResponseDuration',
            'producerSsResponseDuration',
            'requestNwDuration',
            'totalDuration',
            'producerDurationProducerView',
            'responseNwDuration',
            'producerResponseSize',
            'producerDurationClientView',
            'clientResponseSize',
            'producerSsRequestDuration',
            'clientRequestSize',
            'clientSsRequestDuration',
            'producerRequestSize',
            'producerIsDuration'
        ]

        return {
            key: (self.get_boundary_value(value) if key in keys_to_limit else value)
            for (key, value) in document.items()
        }

    def apply_calculations(self, in_doc):
        """
        Calls out all the functions to perform the calculations.
        :param in_doc: The input document.
        :return: Returns the document with the applied calculations.
        """
        in_doc = self._client_calculations(in_doc)
        in_doc = self._producer_calculations(in_doc)
        in_doc = self._pair_calculations(in_doc)
        in_doc = self._limit_calculation_values(in_doc)
        return in_doc

    def match_documents(self, document_a, document_b, orphan=False):
        """
        Tries to match 2 regular documents.
        :param document_a: The input document A.
        :param document_b: The input document B.
        :param orphan: Set to True to match orphan documents.
        :return: Returns True if the given documents match.
        """

        if None in [document_a, document_b]:
            return False

        # Divide document into client and producer
        security_type = document_a.get('securityServerType', None)
        if security_type == 'Client':
            client = document_a
            producer = document_b.get('producer')
        elif security_type == 'Producer':
            producer = document_a
            client = document_b.get('client')
        else:
            # If here, Something is wrong
            self.logger_m.log_error('document_manager',
                                    'Unknown matching type between {0} and {1}'.format(document_a, document_b))
            return False

        # Check if client/producer object exist
        if client is None or producer is None:
            return False

        # Check time exists
        if client.get('requestInTs') is None or producer.get('requestInTs') is None:
            return False

        # Check time difference
        if abs(client['requestInTs'] - producer['requestInTs']) > self.TIME_WINDOW:
            return False

        # Check attribute list
        attributes = self.orphan_comparison_list if orphan else self.COMPARISON_LIST
        for attribute in attributes:
            if client.get(attribute, None) != producer.get(attribute, None):
                return False

        # If here, all matching conditions are OK
        return True

    def find_match(self, document_a, documents_list, orphan=False):
        """
        Performs the regular match for given document in the given document_list.
        :param document_a: The document to be matched.
        :param documents_list: The list of documents to search the match from.
        :param orphan: Set to True to match orphan documents
        :return: Returns the matching document. If no match found, returns None.
        """
        for cur_document in documents_list:
            if self.match_documents(document_a, cur_document, orphan):
                return cur_document
        return None

    @staticmethod
    def create_json(client_document, producer_document, client_hash, producer_hash, message_id):
        """
        Creates the basic JSON document that includes both client and producer
        :param client_document: The client document.
        :param producer_document: The producer document.
        :param client_hash: Client hash.
        :param producer_hash: Producer hash.
        :param message_id: Message_id.
        :return: Returns the document that includes all the fields.
        """
        return {
            'client': client_document,
            'producer': producer_document,
            'clientHash': client_hash,
            'producerHash': producer_hash,
            'messageId': message_id
        }

    def correct_structure(self, doc):
        """
        Adds missing fields for the documents and sets their value to None.
        :param doc: The input document.
        :return: Returns the corrected document.
        """
        for f in self.must_fields:
            if f not in doc:
                doc[f] = None
        return doc

    @staticmethod
    def calculate_hash(_document):
        """
        Hash the given document with MD5 and remove _id & insertTime parameters.
        :param _document: The input documents.
        :return: Returns the monitoringDataTs_document_hash string.
        """
        document = _document.copy()
        doc_hash = None
        if document is not None:
            od = collections.OrderedDict(sorted(document.items()))
            od.pop('_id', None)
            od.pop('insertTime', None)
            od.pop('corrected', None)
            json_str = str(od)
            doc_hash = hashlib.md5(json_str.encode('utf-8')).hexdigest()
        return "{0}_{1}".format(document['monitoringDataTs'], doc_hash)