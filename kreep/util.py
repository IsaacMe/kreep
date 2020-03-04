#---------------------------------------------------------------
# kreep - keystroke recognition and entropy elimination program
#   by Vinnie Monaco
#   www.vmonaco.com
#   contact AT vmonaco DOT com
#
#   Licensed under GPLv3
#
#----------------------------------------------------------------

import dpkt
import socket
import string
import numpy as np
import pandas as pd
import pkg_resources

DATA_PATH = pkg_resources.resource_filename('kreep', 'data/')
LANGUAGE_MODELS = pkg_resources.resource_filename('kreep', 'data/language_models')

KEY_SET = list(string.ascii_lowercase)
INT2KEY = dict(enumerate(sorted(KEY_SET)))
KEY2INT = {v:k for k, v in INT2KEY.items()}

IS_GOOGLE = {}


def ip_to_str(ipv6, address):
    '''
    transform a int ip address to a human readable ip address (ipv4)
    '''
    ip_fam = socket.AF_INET

    if ipv6:
        ip_fam = socket.AF_INET6

    return socket.inet_ntop(ip_fam, address)


def load_pcap(fname, website):
    '''
    Load a pcap (ng) into a pandas DataFrame
    '''
    if fname.endswith('.csv'):
        df = pd.read_csv(fname, index_col=0)
    else:
        rows = []
        for ts, buf in dpkt.pcapng.Reader(open(fname,'rb')):
            rows.extend(parse_eth(buf, ts, website))
        df = pd.DataFrame(rows, columns=['src','dst','frame_time','frame_length','protocol'])
    return df


def parse_eth(buf, ts, website):
    eth = dpkt.ethernet.Ethernet(buf)
    if eth.type == dpkt.ethernet.ETH_TYPE_IP or eth.type == dpkt.ethernet.ETH_TYPE_IP6:
        return parse_ip(eth.data, ts, eth, website)
    return []


def parse_ip(ip, ts, eth, website):
    if ip.p == dpkt.ip.IP_PROTO_TCP and (
            website != 'google' or is_from_google(ip_to_str(eth.type == dpkt.ethernet.ETH_TYPE_IP6, ip.dst))):
        return parse_tcp(ip.data, ts, ip, eth)
    return []


def parse_tcp(tcp, ts, ip, eth):
    if len(tcp.data) > 0 and tcp.dport == 443:  # TODO Ignores HTTP, only HTTPS, no QUIC support
        return parse_tls(tcp, ts, ip, eth)

    return []


def parse_tls(tcp, ts, ip, eth):
    try:
        tls_records, i = dpkt.ssl.tls_multi_factory(tcp.data)
    except (dpkt.ssl.SSL3Exception, dpkt.dpkt.NeedData, dpkt.dpkt.UnpackError):
        return []

    if i < len(tcp.data):
        # TODO Possibly not read all TLS Records due to fragmentation
        pass

    results = []
    for record in tls_records:
        if record.type == 23: # TLS APP DATA
            results.append((ip_to_str(eth.type == dpkt.ethernet.ETH_TYPE_IP6, ip.src) + ':' + str(tcp.sport),
                     ip_to_str(eth.type == dpkt.ethernet.ETH_TYPE_IP6, ip.dst) + ':' + str(tcp.dport), ts * 1000,
                     len(record.data), ip.p))

    return results

def word2idx(word):
    return [KEY2INT[c] for c in word]


def idx2word(idx):
    return ''.join([INT2KEY[c] for c in idx])


def is_from_google(ip):
    if ip in IS_GOOGLE:
        return IS_GOOGLE[ip]

    try:
        is_google = socket.gethostbyaddr(ip)[0].endswith('1e100.net')
        IS_GOOGLE[ip] = is_google
        return is_google
    except socket.herror:
        IS_GOOGLE[ip] = False
        return False


def load_words(fname):
    words = pd.read_csv(fname, header=None).squeeze()

    words = words.dropna()
    words = words.str.lower()
    words = words.drop_duplicates()
    words = words.reset_index(drop=True)

    s = words.str.len()
    words_dict = {}
    for word_len in range(s.min(), s.max()+1):
        idx = words[s==word_len].apply(lambda x: np.array(word2idx(x))).values
        if len(idx) == 0:
            continue
        words_dict[word_len] = words[s==word_len].values

    return words_dict


def load_language(fname):
    from .lm import ARPALanguageModel

    lm = ARPALanguageModel(fname, base_e=False)

    words = pd.Series([w[0] for w in lm.ngrams._data.keys() if len(w)==1])
    words = words.dropna()
    words = words.str.lower()
    words = words[words.str.isalpha()]
    words = words.drop_duplicates()

    s = words.str.len()
    words_dict = {}
    for word_len in range(s.min(), s.max()+1):
        idx = words[s==word_len].apply(lambda x: np.array(word2idx(x))).values
        if len(idx) == 0:
            continue
        words_dict[word_len] = words[s==word_len].values

    def lm_fun(word, history=None, lm=lm):
        return lm.scoreword(word, history)

    return lm_fun, words_dict


def load_bigrams(fname):
    df = pd.read_csv(fname, index_col=[0,1])
    return df
