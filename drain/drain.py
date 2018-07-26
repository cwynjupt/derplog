"""
Description : This file implements the Drain algorithm for log parsing
Author      : LogPAI team
License     : MIT
"""

import re
import os
import numpy as np
import pandas as pd
import fileinput
import hashlib
import json
import yaml
from datetime import datetime


class Logcluster:
    def __init__(self, logTemplate='', logIDL=None):
        self.logTemplate = logTemplate
        if logIDL is None:
            logIDL = []
        self.logIDL = logIDL

    def to_dict(self):
        return {
            'logTemplate': self.logTemplate,
            'logIDL': self.logIDL,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            logTemplate=d['logTemplate'],
            logIDL=d['logIDL'],
        )


class Node:
    def __init__(self, childD=None, depth=0, digitOrToken=None):
        if childD is None:
            childD = dict()
        self.childD = childD
        self.depth = depth
        self.digitOrToken = digitOrToken

    def to_dict(self):
        if type(self.childD) == dict:
            children = { k: v.to_dict() for k, v in self.childD.items() }
        else:
            children = [ v.to_dict() for v in self.childD ]

        return {
            'depth': self.depth,
            'digitOrToken': self.digitOrToken,
            'children': children,
        }

    @classmethod
    def from_dict(cls, d):
        if 'logTemplate' in d.keys():
            return Logcluster.from_dict(d)

        def key_of(k, depth):
            if depth == 0:
                return int(k)
            else:
                return k

        def do_children(children, depth):
            if type(children) == dict:
                return { key_of(k, depth): cls.from_dict(v) for k, v in children.items() }
            else:
                return [ cls.from_dict(v) for v in children ]

        return cls(
            depth=d['depth'],
            digitOrToken=d['digitOrToken'],
            childD=do_children(d['children'], d['depth']),
        )


class LogParser:
    def __init__(self, indir='./', outdir='./result/', depth=4, st=0.4, maxChild=100, rex=[], verbose=False):
        """
        Attributes
        ----------
            rex : regular expressions used in preprocessing (step1)
            path : the input path stores the input log file name
            depth : depth of all leaf nodes
            st : similarity threshold
            maxChild : max number of children of an internal node
            logName : the name of the input file containing raw log messages
            savePath : the output path stores the file containing structured logs
        """
        self.path = indir
        self.depth = depth - 2
        self.st = st
        self.maxChild = maxChild
        self.savePath = outdir
        self.df_log = None
        self.rex = rex
        self.rootNode = Node()
        self.logCluL = []
        self.verbose = verbose

    def hasNumbers(self, s):
        return any(char.isdigit() for char in s)

    def treeSearch(self, rn, seq):
        retLogClust = None

        seqLen = len(seq)
        if seqLen not in rn.childD:
            return retLogClust

        parentn = rn.childD[seqLen]

        currentDepth = 1
        for token in seq:
            if currentDepth >= self.depth or currentDepth > seqLen:
                break

            if token in parentn.childD:
                parentn = parentn.childD[token]
            elif '<*>' in parentn.childD:
                parentn = parentn.childD['<*>']
            else:
                return retLogClust
            currentDepth += 1

        logClustL = parentn.childD

        retLogClust = self.fastMatch(logClustL, seq)

        return retLogClust

    def addSeqToPrefixTree(self, rn, logClust):
        seqLen = len(logClust.logTemplate)
        if seqLen not in rn.childD:
            firtLayerNode = Node(depth=1, digitOrToken=seqLen)
            rn.childD[seqLen] = firtLayerNode
        else:
            firtLayerNode = rn.childD[seqLen]

        parentn = firtLayerNode

        currentDepth = 1
        for token in logClust.logTemplate:

            #Add current log cluster to the leaf node
            if currentDepth >= self.depth or currentDepth > seqLen:
                if len(parentn.childD) == 0:
                    parentn.childD = [logClust]
                else:
                    parentn.childD.append(logClust)
                break

            #If token not matched in this layer of existing tree.
            if token not in parentn.childD:
                if not self.hasNumbers(token):
                    if '<*>' in parentn.childD:
                        if len(parentn.childD) < self.maxChild:
                            newNode = Node(depth=currentDepth + 1, digitOrToken=token)
                            parentn.childD[token] = newNode
                            parentn = newNode
                        else:
                            parentn = parentn.childD['<*>']
                    else:
                        if len(parentn.childD)+1 < self.maxChild:
                            newNode = Node(depth=currentDepth+1, digitOrToken=token)
                            parentn.childD[token] = newNode
                            parentn = newNode
                        elif len(parentn.childD)+1 == self.maxChild:
                            newNode = Node(depth=currentDepth+1, digitOrToken='<*>')
                            parentn.childD['<*>'] = newNode
                            parentn = newNode
                        else:
                            parentn = parentn.childD['<*>']

                else:
                    if '<*>' not in parentn.childD:
                        newNode = Node(depth=currentDepth+1, digitOrToken='<*>')
                        parentn.childD['<*>'] = newNode
                        parentn = newNode
                    else:
                        parentn = parentn.childD['<*>']

            #If the token is matched
            else:
                parentn = parentn.childD[token]

            currentDepth += 1

    #seq1 is template
    def seqDist(self, seq1, seq2):
        assert len(seq1) == len(seq2)
        simTokens = 0
        numOfPar = 0

        for token1, token2 in zip(seq1, seq2):
            if token1 == '<*>':
                numOfPar += 1
                continue
            if token1 == token2:
                simTokens += 1

        retVal = float(simTokens) / len(seq1)

        return retVal, numOfPar


    def fastMatch(self, logClustL, seq):
        retLogClust = None

        maxSim = -1
        maxNumOfPara = -1
        maxClust = None

        for logClust in logClustL:
            curSim, curNumOfPara = self.seqDist(logClust.logTemplate, seq)
            if curSim>maxSim or (curSim==maxSim and curNumOfPara>maxNumOfPara):
                maxSim = curSim
                maxNumOfPara = curNumOfPara
                maxClust = logClust

        if maxSim >= self.st:
            retLogClust = maxClust

        return retLogClust

    def getTemplate(self, seq1, seq2):
        assert len(seq1) == len(seq2)
        retVal = []

        i = 0
        for word in seq1:
            if word == seq2[i]:
                retVal.append(word)
            else:
                retVal.append('<*>')

            i += 1

        return retVal

    def outputResult(self, logClustL, logName):
        log_templates = [0] * self.df_log.shape[0]
        log_templateids = [0] * self.df_log.shape[0]
        df_events = []

        if not os.path.exists(self.savePath):
            os.makedirs(self.savePath)

        for logClust in logClustL:
            template_str = ' '.join(logClust.logTemplate)
            occurrence = len(logClust.logIDL)
            template_id = hashlib.md5(template_str.encode('utf-8')).hexdigest()[0:8]
            for logID in logClust.logIDL:
                logID -= 1
                log_templates[logID] = template_str
                log_templateids[logID] = template_id
            df_events.append([template_id, template_str, occurrence])

        df_event = pd.DataFrame(df_events, columns=['EventId', 'EventTemplate', 'Occurrences'])
        self.df_log['EventId'] = log_templateids
        self.df_log['EventTemplate'] = log_templates

        # self.df_log.drop(['Content'], inplace=True, axis=1)
        if logName:
            self.df_log.to_csv(os.path.join(self.savePath, logName + '_structured.csv'), index=False)
        else:
            print(self.df_log)


        occ_dict = dict(self.df_log['EventTemplate'].value_counts())
        df_event = pd.DataFrame()
        df_event['EventTemplate'] = self.df_log['EventTemplate'].unique()
        df_event['EventId'] = df_event['EventTemplate']\
                              .map(lambda x: hashlib.md5(x.encode('utf-8')).hexdigest()[0:8])
        df_event['Occurrences'] = df_event['EventTemplate'].map(occ_dict)
        if logName:
            df_event.to_csv(os.path.join(self.savePath, logName + '_templates.csv'),
                            index=False, columns=["EventId", "EventTemplate", "Occurrences"])
        else:
            print(df_event)


    def printTree(self, node=None, dep=0):
        if not node:
            node = self.rootNode

        pStr = ''
        for i in range(dep):
            pStr += '\t'

        if node.depth == 0:
            pStr += 'Root'
        elif node.depth == 1:
            pStr += '<' + str(node.digitOrToken) + '>'
        else:
            pStr += node.digitOrToken

        print(pStr)

        if node.depth == self.depth:
            return 1
        for child in node.childD:
            self.printTree(node.childD[child], dep+1)


    def saveTree(self, outfile=None):
        meta = {
            'depth': self.depth,
            'st': self.st,
            'maxChild': self.maxChild,
            'rex': self.rex,
        }
        tree = self.rootNode.to_dict()
        out = {
            'meta': meta,
            'tree': tree,
        }

        if outfile:
            with open(outfile, 'w') as f:
                json.dump(out, f)
        else:
            return json.dumps(out)


    def loadTree(self, infile):
        with open(infile, 'r') as f:
            tree = yaml.load(f)

        if not tree:
            return

        self.depth = tree['meta']['depth']
        self.st = tree['meta']['st']
        self.maxChild = tree['meta']['maxChild']
        self.rex = tree['meta']['rex']

        self.rootNode = Node.from_dict(tree['tree'])


    def parse(self, logName=None):
        count = 0

        # If we don't get a log file, parse stdin
        if logName:
            if self.verbose:
                print('Parsing file: ' + os.path.join(self.path, logName))
            self.load_data(logName)
            iterator = self.df_log.iterrows
        else:
            if self.verbose:
                print('Parsing stdin...')
            iterator = fileinput.input
            self.df_log = pd.DataFrame(columns=['LineId', 'Content'])

        start_time = datetime.now()
        for line in iterator():
            # df iterator returns a tuple we have to parse
            if isinstance(line, tuple):
                line = line[1]
            else:
                line = pd.Series({'LineId': count, 'Content': line.strip()})
                self.df_log = self.df_log.append(line, ignore_index=True)

            self.parseLine(line)

            count += 1
            if self.verbose and logName and (count % 1000 == 0 or count == len(self.df_log)):
                print('Processed {0:.1f}% of log lines.'.format(count * 100.0 / len(self.df_log)))

        if self.verbose:
            print('Parsing done. [Time taken: {!s}]'.format(datetime.now() - start_time))

        # self.outputResult(self.logCluL, logName)
        # self.printTree(self.rootNode)
        # import pdb; pdb.set_trace()

    def parseLine(self, line):
        logID = line['LineId']
        logmessageL = self.preprocess(line['Content']).strip().split()
        # logmessageL = filter(lambda x: x != '', re.split('[\s=:,]', self.preprocess(line['Content'])))
        matchCluster = self.treeSearch(self.rootNode, logmessageL)

        #Match no existing log cluster
        if matchCluster is None:
            newCluster = Logcluster(logTemplate=logmessageL, logIDL=[logID])
            self.logCluL.append(newCluster)
            self.addSeqToPrefixTree(self.rootNode, newCluster)

        #Add the new log message to the existing cluster
        else:
            newTemplate = self.getTemplate(logmessageL, matchCluster.logTemplate)
            matchCluster.logIDL.append(logID)
            if ' '.join(newTemplate) != ' '.join(matchCluster.logTemplate):
                matchCluster.logTemplate = newTemplate

    def load_data(self, logName):
        self.df_log = self.log_to_dataframe(os.path.join(self.path, logName))

    def preprocess(self, line):
        for currentRex in self.rex:
            line = re.sub(currentRex, '<*>', line)
        return line

    def log_to_dataframe(self, log_file):
        """ Function to transform log file to dataframe
        """
        log_messages = []
        linecount = 0
        with open(log_file, 'r') as fin:
            lines = fin.readlines()
        logdf = pd.DataFrame(lines, columns=['Content'])
        logdf.insert(0, 'LineId', None)
        logdf['LineId'] = [i + 1 for i in range(len(lines))]
        return logdf
