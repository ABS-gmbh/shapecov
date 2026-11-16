// Package xdr is a small stand-in for github.com/stellar/go-stellar-sdk/xdr,
// used only by the analyzer tests. It declares the types, fields and methods
// the fixtures need, with the names and signatures of SDK v0.8.0
// (scripts/check-stubs.sh compares them with the real package).
package xdr

type (
	Uint32   uint32
	Int64    int64
	Uint64   uint64
	Uint256  [32]byte
	Hash     [32]byte
	String64 string
)

type DataValue []byte

type CryptoKeyType int32

const (
	CryptoKeyTypeKeyTypeEd25519      CryptoKeyType = 0
	CryptoKeyTypeKeyTypeMuxedEd25519 CryptoKeyType = 256
)

type PublicKeyType int32

type PublicKey struct {
	Type    PublicKeyType
	Ed25519 *Uint256
}

type AccountId PublicKey

func (aid AccountId) Address() string { return "" }

type MuxedAccountMed25519 struct {
	Id      Uint64
	Ed25519 Uint256
}

type MuxedAccount struct {
	Type     CryptoKeyType
	Ed25519  *Uint256
	Med25519 *MuxedAccountMed25519
}

func (m MuxedAccount) Address() string              { return "" }
func (m *MuxedAccount) GetAddress() (string, error) { return "", nil }
func (m MuxedAccount) ToAccountId() AccountId       { return AccountId{} }
func (m MuxedAccount) GetMed25519() (MuxedAccountMed25519, bool) {
	return MuxedAccountMed25519{}, false
}
func (m MuxedAccount) MustMed25519() MuxedAccountMed25519 { return *m.Med25519 }

type MemoType int32

const (
	MemoTypeMemoNone MemoType = 0
	MemoTypeMemoText MemoType = 1
	MemoTypeMemoId   MemoType = 2
)

type Memo struct {
	Type    MemoType
	Text    *string
	Id      *Uint64
	Hash    *Hash
	RetHash *Hash
}

func (u Memo) MustText() string        { return *u.Text }
func (u Memo) GetText() (string, bool) { return "", false }
func (u Memo) MustId() Uint64          { return *u.Id }
func (u Memo) GetId() (Uint64, bool)   { return 0, false }

type ScValType int32

const (
	ScValTypeScvVec            ScValType = 16
	ScValTypeScvMap            ScValType = 17
	ScValTypeScvString         ScValType = 14
	ScValTypeScvLedgerKeyNonce ScValType = 21
)

type (
	ScString string
	ScSymbol string
	ScBytes  []byte
	ScVec    []ScVal
	ScMap    []ScMapEntry
)

type ScMapEntry struct {
	Key ScVal
	Val ScVal
}

type ScNonceKey struct {
	Nonce Int64
}

type ScVal struct {
	Type     ScValType
	Bytes    *ScBytes
	Str      *ScString
	Sym      *ScSymbol
	Vec      **ScVec
	Map      **ScMap
	Address  *ScAddress
	NonceKey *ScNonceKey
}

func (u ScVal) MustStr() ScString             { return *u.Str }
func (u ScVal) GetStr() (ScString, bool)      { return "", false }
func (u ScVal) MustSym() ScSymbol             { return *u.Sym }
func (u ScVal) MustVec() *ScVec               { return *u.Vec }
func (u ScVal) GetVec() (*ScVec, bool)        { return nil, false }
func (u ScVal) MustMap() *ScMap               { return *u.Map }
func (u ScVal) GetMap() (*ScMap, bool)        { return nil, false }
func (u ScVal) MustAddress() ScAddress        { return *u.Address }
func (u ScVal) GetAddress() (ScAddress, bool) { return ScAddress{}, false }

type ScAddressType int32

type ContractId Hash

type MuxedEd25519Account struct {
	Id      Uint64
	Ed25519 Uint256
}

type ScAddress struct {
	Type         ScAddressType
	AccountId    *AccountId
	ContractId   *ContractId
	MuxedAccount *MuxedEd25519Account
}

func (a ScAddress) String() (string, error) { return "", nil }

type ScSpecType int32

type ScSpecTypeOption struct {
	ValueType ScSpecTypeDef
}

type ScSpecTypeVec struct {
	ElementType ScSpecTypeDef
}

type ScSpecTypeDef struct {
	Type   ScSpecType
	Option *ScSpecTypeOption
	Vec    *ScSpecTypeVec
}

type SorobanCredentialsType int32

const (
	SorobanCredentialsTypeSorobanCredentialsSourceAccount SorobanCredentialsType = 0
	SorobanCredentialsTypeSorobanCredentialsAddress       SorobanCredentialsType = 1
)

type SorobanAddressCredentials struct {
	Address                   ScAddress
	Nonce                     Int64
	SignatureExpirationLedger Uint32
	Signature                 ScVal
}

type SorobanCredentials struct {
	Type    SorobanCredentialsType
	Address *SorobanAddressCredentials
}

func (u SorobanCredentials) MustAddress() SorobanAddressCredentials { return *u.Address }
func (u SorobanCredentials) GetAddress() (SorobanAddressCredentials, bool) {
	return SorobanAddressCredentials{}, false
}

type InvokeContractArgs struct {
	ContractAddress ScAddress
	FunctionName    ScSymbol
	Args            []ScVal
}

type SorobanAuthorizedFunctionType int32

type SorobanAuthorizedFunction struct {
	Type       SorobanAuthorizedFunctionType
	ContractFn *InvokeContractArgs
}

func (u SorobanAuthorizedFunction) MustContractFn() InvokeContractArgs { return *u.ContractFn }
func (u SorobanAuthorizedFunction) GetContractFn() (InvokeContractArgs, bool) {
	return InvokeContractArgs{}, false
}

type SorobanAuthorizedInvocation struct {
	Function       SorobanAuthorizedFunction
	SubInvocations []SorobanAuthorizedInvocation
}

type SorobanAuthorizationEntry struct {
	Credentials    SorobanCredentials
	RootInvocation SorobanAuthorizedInvocation
}

type HostFunctionType int32

type HostFunction struct {
	Type           HostFunctionType
	InvokeContract *InvokeContractArgs
}

func (u HostFunction) MustInvokeContract() InvokeContractArgs { return *u.InvokeContract }

type InvokeHostFunctionOp struct {
	HostFunction HostFunction
	Auth         []SorobanAuthorizationEntry
}

type Asset struct{}

func NewCreditAsset(code string, issuer string) (Asset, error) { return Asset{}, nil }
func (a Asset) ContractID(passphrase string) ([32]byte, error) { return [32]byte{}, nil }

type PaymentOp struct {
	Destination MuxedAccount
	Asset       Asset
	Amount      Int64
}

type CreateAccountOp struct {
	Destination     AccountId
	StartingBalance Int64
}

type ManageDataOp struct {
	DataName  String64
	DataValue *DataValue
}

type OperationType int32

const (
	OperationTypeCreateAccount      OperationType = 0
	OperationTypePayment            OperationType = 1
	OperationTypeInvokeHostFunction OperationType = 24
)

type OperationBody struct {
	Type                 OperationType
	CreateAccountOp      *CreateAccountOp
	PaymentOp            *PaymentOp
	ManageDataOp         *ManageDataOp
	InvokeHostFunctionOp *InvokeHostFunctionOp
}

func (u OperationBody) MustCreateAccountOp() CreateAccountOp { return *u.CreateAccountOp }
func (u OperationBody) MustPaymentOp() PaymentOp             { return *u.PaymentOp }
func (u OperationBody) GetPaymentOp() (PaymentOp, bool)      { return PaymentOp{}, false }
func (u OperationBody) MustManageDataOp() ManageDataOp       { return *u.ManageDataOp }
func (u OperationBody) MustInvokeHostFunctionOp() InvokeHostFunctionOp {
	return *u.InvokeHostFunctionOp
}
func (u OperationBody) GetInvokeHostFunctionOp() (InvokeHostFunctionOp, bool) {
	return InvokeHostFunctionOp{}, false
}

type Operation struct {
	SourceAccount *MuxedAccount
	Body          OperationBody
}

type TransactionEnvelope struct{}

func (e TransactionEnvelope) SourceAccount() MuxedAccount  { return MuxedAccount{} }
func (e TransactionEnvelope) FeeBumpAccount() MuxedAccount { return MuxedAccount{} }
func (e TransactionEnvelope) IsFeeBump() bool              { return false }
func (e TransactionEnvelope) Operations() []Operation      { return nil }
func (e TransactionEnvelope) Memo() Memo                   { return Memo{} }

type TransactionResultPair struct{}

func (r TransactionResultPair) Successful() bool { return false }

type LedgerEntryType int32

const (
	LedgerEntryTypeAccount      LedgerEntryType = 0
	LedgerEntryTypeContractData LedgerEntryType = 6
)

type LedgerEntryChangeType int32

const LedgerEntryChangeTypeLedgerEntryCreated LedgerEntryChangeType = 0

type AccountEntry struct {
	AccountId AccountId
}

type ContractDataEntry struct {
	Contract ScAddress
	Key      ScVal
	Val      ScVal
}

type LedgerEntryData struct {
	Type         LedgerEntryType
	Account      *AccountEntry
	ContractData *ContractDataEntry
}

func (u LedgerEntryData) MustAccount() AccountEntry           { return *u.Account }
func (u LedgerEntryData) MustContractData() ContractDataEntry { return *u.ContractData }

type LedgerEntry struct {
	LastModifiedLedgerSeq Uint32
	Data                  LedgerEntryData
}

type LedgerEntryChange struct {
	Type LedgerEntryChangeType
}

type LedgerEntryChanges []LedgerEntryChange

type TransactionMeta struct{}

// BuildAssets parses "CODE:ISSUER" and "native" strings; it rejects anything else.
func BuildAssets(s string) ([]Asset, error) { return nil, nil }
