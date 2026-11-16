# Differential run report

Cases: 7392 generated from the Protocol 30 XDR schema (stellar-xdr v30.0). Reference decoder: stellar-xdr 30.0.0 (reference).

Schema cells exercised by valid cases (union arms and enum members): 837 of 1188 (70.5%).

## Disagreements with the reference, by case kind

Each cell is `disagreements / cases run` for that SDK. `valid` rows are values the reference decodes and re-encodes byte-for-byte; the other rows carry one injected fault.

| Case kind | js (@stellar/stellar-sdk 17.4.0) | python (stellar-sdk 17.0.1) | python-xdr (stellar-xdr (Python) 0.2.1) | go (go-stellar-sdk v0.9.0) | java (network.lightsail:stellar-sdk 6.0.0) |
|---|---|---|---|---|---|
| valid | 0 / 3624 | 0 / 3808 | 0 / 3768 | 8 / 3808 | 0 / 3808 |
| bool_not_01 | 26 / 26 | 26 / 26 | 26 / 26 | 26 / 26 | 26 / 26 |
| enum_unknown | 0 / 738 | 0 / 748 | 0 / 747 | 0 / 748 | 0 / 748 |
| len_huge | 0 / 336 | 0 / 364 | 0 / 364 | 0 / 364 | 0 / 364 |
| len_over_max | 0 / 204 | 0 / 218 | 0 / 218 | 0 / 218 | 0 / 218 |
| opt_flag_not_01 | 0 / 136 | 145 / 145 | 0 / 143 | 0 / 145 | 0 / 145 |
| pad_nonzero | 0 / 151 | 160 / 160 | 0 / 160 | 0 / 160 | 0 / 160 |
| trailing | 0 / 914 | 0 / 952 | 0 / 942 | 222 / 952 | 952 / 952 |
| truncated | 0 / 914 | 0 / 952 | 0 / 942 | 0 / 952 | 0 / 952 |

## Reference notes

- reference accepts fault bool_not_01: 26

## Clusters

Disagreements grouped by SDK, class, case kind and message or fault site. A cluster is a lead to triage, not a confirmed bug.

| SDK | Class | Case kind | Signature | Cases | Example |
|---|---|---|---|---|---|
| go | accepts_invalid | trailing | `+N bytes` | 222 | `Value/trailing1` |
| go | reencodes_differently | valid | `AAAAAMoVkzRZKNPXkgnTRNorpGZrLKJZNlNcZfSppNDcN` | 1 | `SponsorshipDescriptor/v0` |
| go | reencodes_differently | valid | `AAAAAMNXNyANiRTNeoPNkgzJXPCskh+IFgfyztNMNyOzqNEN` | 1 | `SponsorshipDescriptor/v5` |
| go | rejects_valid | valid | `xdr:Marshal: can't marshal nil pointer '**xdr.AccountId'` | 6 | `SponsorshipDescriptor/v1` |
| go | rejects_valid | bool_not_01 | `decoding Bool: xdr:DecodeBool: bool not N or N - read: 'N'` | 4 | `EvictionIterator/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding DiagnosticEvent: decoding Bool: xdr:DecodeBool: bool not N or N - read: 'N'` | 2 | `SorobanTransactionMeta/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding ContractEvent: decoding ContractEventBody: decoding ContractEventVN: decoding ScVal: decoding Bool: x` | 2 | `OperationMetaV2/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding TimeSlicedNodeData: decoding Bool: xdr:DecodeBool: bool not N or N - read: 'N'` | 2 | `TopologyResponseBodyV2/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding TopologyResponseBodyVN: decoding TimeSlicedNodeData: decoding Bool: xdr:DecodeBool: bool not N or N -` | 2 | `SurveyResponseBody/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding SorobanDelegateSignature: decoding SorobanDelegateSignature: decoding SorobanDelegateSignature: decod` | 2 | `SorobanDelegateSignature/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding ScMap: decoding ScMapEntry: decoding ScVal: decoding Bool: xdr:DecodeBool: bool not N or N - read: 'N` | 1 | `SCContractInstance/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding ContractEvent: decoding ContractEventBody: decoding ContractEventVN: decoding ScVal: decoding ScMap: ` | 1 | `DiagnosticEvent/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding ScVal: decoding Bool: xdr:DecodeBool: bool not N or N - read: 'N'` | 1 | `SorobanTransactionMeta/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding SorobanTransactionMeta: decoding DiagnosticEvent: decoding Bool: xdr:DecodeBool: bool not N or N - re` | 1 | `TransactionMetaV3/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding TransactionMetaVN: decoding SorobanTransactionMeta: decoding ScVal: decoding Bool: xdr:DecodeBool: bo` | 1 | `TransactionMeta/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding TransactionResultMetaVN: decoding TransactionMeta: decoding TransactionMetaVN: decoding OperationMeta` | 1 | `LedgerCloseMetaV2/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding Bool: xdr:DecodeBool: bool not N or N - read: '-N'` | 1 | `TimeSlicedNodeData/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding SorobanDelegateSignature: decoding SorobanDelegateSignature: decoding ScVal: decoding Bool: xdr:Decod` | 1 | `SorobanAddressCredentialsWithDelegates/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding SorobanAddressCredentialsWithDelegates: decoding SorobanDelegateSignature: decoding SorobanDelegateSi` | 1 | `SorobanCredentials/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding SorobanAuthorizationEntry: decoding SorobanAuthorizedInvocation: decoding SorobanAuthorizedInvocation` | 1 | `InvokeHostFunctionOp/bool_not_010` |
| go | rejects_valid | bool_not_01 | `decoding HashIdPreimageSorobanAuthorizationWithAddress: decoding SorobanAuthorizedInvocation: decoding Soroban` | 1 | `HashIDPreimage/bool_not_011` |
| go | rejects_valid | bool_not_01 | `decoding TransactionSignaturePayloadTaggedTransaction: decoding FeeBumpTransaction: decoding FeeBumpTransactio` | 1 | `TransactionSignaturePayload/bool_not_011` |
| java | accepts_invalid | trailing | `+N bytes` | 952 | `Value/trailing0` |
| java | rejects_valid | bool_not_01 | `IOException: Invalid boolean value: N, must be N or N per RFC N` | 22 | `EvictionIterator/bool_not_010` |
| java | rejects_valid | bool_not_01 | `IOException: Invalid boolean value: -N, must be N or N per RFC N` | 4 | `TimeSlicedNodeData/bool_not_010` |
| js | rejects_valid | bool_not_01 | `EvictionIterator.isCurrBucket: invalid bool discriminant N` | 2 | `EvictionIterator/bool_not_010` |
| js | rejects_valid | bool_not_01 | `TimeSlicedNodeData.isValidator: invalid bool discriminant N` | 2 | `TimeSlicedNodeData/bool_not_010` |
| js | rejects_valid | bool_not_01 | `TopologyResponseBodyVN.nodeData.isValidator: invalid bool discriminant N` | 2 | `TopologyResponseBodyV2/bool_not_010` |
| js | rejects_valid | bool_not_01 | `SurveyResponseBody.surveyTopologyResponseVN.topologyResponseBodyVN.nodeData.isValidator: invalid bool discrimi` | 2 | `SurveyResponseBody/bool_not_010` |
| js | rejects_valid | bool_not_01 | `ScContractInstance.storage.value[N].val.scvBool.b: invalid bool discriminant N` | 1 | `SCContractInstance/bool_not_010` |
| js | rejects_valid | bool_not_01 | `DiagnosticEvent.inSuccessfulContractCall: invalid bool discriminant N` | 1 | `DiagnosticEvent/bool_not_010` |
| js | rejects_valid | bool_not_01 | `DiagnosticEvent.event.body.vN.vN.topics[N].scvMap.map.value[N].key.scvBool.b: invalid bool discriminant N` | 1 | `DiagnosticEvent/bool_not_011` |
| js | rejects_valid | bool_not_01 | `SorobanTransactionMeta.returnValue.scvBool.b: invalid bool discriminant N` | 1 | `SorobanTransactionMeta/bool_not_010` |
| js | rejects_valid | bool_not_01 | `SorobanTransactionMeta.diagnosticEvents[N].inSuccessfulContractCall: invalid bool discriminant N` | 1 | `SorobanTransactionMeta/bool_not_011` |
| js | rejects_valid | bool_not_01 | `TransactionMetaVN.sorobanMeta.value.diagnosticEvents[N].inSuccessfulContractCall: invalid bool discriminant N` | 1 | `TransactionMetaV3/bool_not_011` |
| js | rejects_valid | bool_not_01 | `OperationMetaVN.events[N].body.vN.vN.topics[N].scvBool.b: invalid bool discriminant N` | 1 | `OperationMetaV2/bool_not_011` |
| js | rejects_valid | bool_not_01 | `TransactionMetaVN.diagnosticEvents[N].inSuccessfulContractCall: invalid bool discriminant N` | 1 | `TransactionMetaV4/bool_not_011` |
| js | rejects_valid | bool_not_01 | `InvokeHostFunctionSuccessPreImage.events[N].body.vN.vN.topics[N].scvBool.b: invalid bool discriminant N` | 1 | `InvokeHostFunctionSuccessPreImage/bool_not_011` |
| js | rejects_valid | bool_not_01 | `TransactionMeta.vN.vN.sorobanMeta.value.returnValue.scvBool.b: invalid bool discriminant N` | 1 | `TransactionMeta/bool_not_010` |
| js | rejects_valid | bool_not_01 | `LedgerCloseMetaVN.txProcessing[N].txApplyProcessing.vN.vN.operations[N].changes[N].ledgerEntryState.state.data` | 1 | `LedgerCloseMetaV2/bool_not_011` |
| js | rejects_valid | bool_not_01 | `SorobanDelegateSignature.nestedDelegates[N].nestedDelegates[N].nestedDelegates[N].nestedDelegates[N].signature` | 1 | `SorobanDelegateSignature/bool_not_011` |
| js | rejects_valid | bool_not_01 | `SorobanAddressCredentialsWithDelegates.delegates[N].nestedDelegates[N].signature.scvBool.b: invalid bool discr` | 1 | `SorobanAddressCredentialsWithDelegates/bool_not_010` |
| js | rejects_valid | bool_not_01 | `SorobanAddressCredentialsWithDelegates.delegates[N].nestedDelegates[N].nestedDelegates[N].nestedDelegates[N].n` | 1 | `SorobanAddressCredentialsWithDelegates/bool_not_011` |
| js | rejects_valid | bool_not_01 | `SorobanCredentials.sorobanCredentialsAddressWithDelegates.addressWithDelegates.delegates[N].nestedDelegates[N]` | 1 | `SorobanCredentials/bool_not_011` |
| js | rejects_valid | bool_not_01 | `InvokeHostFunctionOp.auth[N].rootInvocation.subInvocations[N].subInvocations[N].subInvocations[N].subInvocatio` | 1 | `InvokeHostFunctionOp/bool_not_010` |
| js | rejects_valid | bool_not_01 | `HashIdPreimage.envelopeTypeSorobanAuthorizationWithAddress.sorobanAuthorizationWithAddress.invocation.subInvoc` | 1 | `HashIDPreimage/bool_not_011` |
| js | rejects_valid | bool_not_01 | `TransactionSignaturePayload.taggedTransaction.envelopeTypeTxFeeBump.feeBump.innerTx.envelopeTypeTx.vN.tx.opera` | 1 | `TransactionSignaturePayload/bool_not_011` |
| python | accepts_invalid | pad_nonzero | `N pad byte(s)` | 160 | `Value/pad_nonzero0` |
| python | accepts_invalid | opt_flag_not_01 | `flag=N` | 145 | `SCPStatement/opt_flag_not_010` |
| python | reencodes_differently | bool_not_01 | `/////wAAAAH//////////w==` | 1 | `EvictionIterator/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAGAAAAAAAAAAA==` | 1 | `EvictionIterator/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAAEAAAABAAAADgAAAAxiOSNwMDlhYlktXNAAAAAAAAAAQ==` | 1 | `SCContractInstance/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAAAAAAAAAAAAAAAAAAAAAAADAAAABgAgAAAAAAAAAAAADQAAAAGcAAAAAAAACYAAAAAAAAAA//////////NAAAAIACAAAAAAAAE=` | 1 | `DiagnosticEvent/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAAAAAAAAAAAAQAAAAAAAAACAAAAAwAAAAAAAAARAAAAAQAAAAMAAAAUAAAABKHUgwNAAAAAAAAAAQAAAAoAAAAAAAAAAf////////` | 1 | `DiagnosticEvent/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAAB//////////wAAAAAAAAABNQuGNdNU+sAAAABAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAVACAAAAAAAAEAAAAAAAAAAQAAAAEAAAA` | 1 | `SorobanTransactionMeta/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAACAAAAAAAAAAIAAAAAAAAAA//////////NAAAAAAAAABQAgAAAAAAABAAAAAQAAAAEAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAwAIA` | 1 | `SorobanTransactionMeta/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAIAAAABgAAAAAAAAAIAAAAADZgxCWztGpPcfCwlDNzqjUhNZhTNfcBNfIcJGXCFsxX//////////wAAAAAAAAABKZCBMQAAAABhoc` | 1 | `TransactionMetaV3/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAMAAAACAAAABW/T/QKNGpauQqyMNNhNiJqmNqPZaNeCVAKBGiNQsTNPAAAABHINcAAAACAAAAAJcxsxYNPluNYBBoAipUU/pOgVnl` | 1 | `OperationMetaV2/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAIAAAAEAAAAAAAAAAMAAAAAWINHKEWqePOEMNvBqlDzTucPNANcNOKmmHNmiRtaNUAAAACXyNAAAAAAAXYsNONgQAAAAAAAAAAAAA` | 1 | `TransactionMetaV4/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAAAAAAEAAAACAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAPAAAACDFfOSNZYmNiAAAAAAAAAAAAAAACAAAAAAAAAAMAAAADAAAAAAAAAAOAAA` | 1 | `InvokeHostFunctionSuccessPreImage/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAwAAAAAAAAACAAAAAAAAAAAAAAADAAAAAONLmENqNWNtNuThLQlhQNHJTNPBEN+VZsacpDwNdAAAAB/zDfFNPX+NAAAAAIKzudi/pliadz` | 1 | `TransactionMeta/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAAAAIAAAAAAAAXodrkTLCVNnlgNyOXqBNBNgQKNHKFNqWLLxatxnSmV/////yYAzRQNvXDldN+htsNHPRpCRcaANrpZxqPBRwsJRaP` | 1 | `LedgerCloseMetaV2/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `/////wAAAAD/////AAAAAIAAAACAAAAAiftdNgAAAAEAAAAAAAAAAQ==` | 1 | `TimeSlicedNodeData/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `gAAAAP////NbYxEo/////NAAAACAAAAAgAAAAAAAAAEAAAABgAAAAA==` | 1 | `TimeSlicedNodeData/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAQAAAADWNoNgIlERFKCRAHNszhexhRNozwbKjPNjlRK+NpXZwAAAARZYVktAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAA` | 1 | `TopologyResponseBodyV2/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAgAAAADNmvqqNnM+jdNYHcN+kwkqKNXQEVmUKM/naJgbNmWjNQAAAARPgDBCAAAAAAAAAAHHVonNOjjdjf//////////ACAAAAAAAAEAAA` | 1 | `TopologyResponseBodyV2/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAgAAAAIAAAAAefNEkeNzlCCNGNqVNGdXrrNnnoKoaWAgWCITyqaxeoAAAADIGJZAIAAAAAAAAAA///////////jIrWMNXNUvQAAAAAAAAA` | 1 | `SurveyResponseBody/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAAAgAAAAEAAAAAPwWbMy+FGLNfItLXuAFMeyNEfNPGCNXeNKNQFNXMoAAAAAACAAAAAAAAEAAAAAAAAAASVZxmRknkVNZMziWM/sNUMAAAAA` | 1 | `SurveyResponseBody/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAABCNCLWiUYVMGBNq+NLnPdNvsQWOEOpGNGdRNrkBCQHsAAAABIAAAAAAAAACAAAAAAAAAAANguhNKeeNPwQNqa+NNNpPSkNTVNjtNtzXaVN` | 1 | `SorobanDelegateSignature/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAABBQCqENTNIkeB+upNQXbeNOWtNElEjCoyiANuGbHOiA//////////NAAAAAAAAADwAAAAAAAAACAAAAAfyYcWNI+FheTPUWkDJw+QNbXXY` | 1 | `SorobanAddressCredentialsWithDelegates/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAABQAAAAAAAAABxFhRMFdCnfMRJGNLgNItmPBXLNkSBOSIJvNYjVONkwAIAAAAAAAAF+DdNIAAAAD/////wAAAAEAAAADAAAAAFxSNrOQNqy` | 1 | `SorobanAddressCredentialsWithDelegates/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAwAAAAUAAAAAAAAAAcDabNvjXZzWwUwNLaNMjPiaNMtImfedlRANsXNVLAAAAAAAAAADGIIaaAAAADwAAACBiYyBZIFgxOWMgXzBZMFgwW` | 1 | `SorobanCredentials/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `AAAAAwAAAAAAAAAENZXuTlMSToylMniHgNkUkmNAqvdpEfNPNxtAI+gquaNnanbkMMmeQgr+Nky/VnK/xUGGoMtdJdcNBpCNLjdowAAAAEAAAA` | 1 | `InvokeHostFunctionOp/bool_not_010` |
| python | reencodes_differently | bool_not_01 | `AAAACtzoKensIZIANwxlpNgB+qxUWRCeHQ/XANXnhGqdDIqMgAAAAAAAAAAAAAABAAAAAAAAAAAejDsQNjitNRNsnbHknsMdForTNMmHDANAQc` | 1 | `HashIDPreimage/bool_not_011` |
| python | reencodes_differently | bool_not_01 | `zUyqKPdHSNGRmPSMFfTi+/WFfN+OhNDNXINAvsSLNsAAAAFAAAAADNpaN+EAVbbNdzffjInCRRwZpALmNRVdK+GwKkZNAAAAAAAAAAEAAAACAA` | 1 | `TransactionSignaturePayload/bool_not_011` |
| python-xdr | rejects_valid | bool_not_01 | `XdrDecodeError: invalid bool N at offset N` | 26 | `EvictionIterator/bool_not_010` |
