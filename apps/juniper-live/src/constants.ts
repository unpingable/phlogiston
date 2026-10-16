export const SPACE_TYPE =
  "net.sp00ky.juniper-pds.authority.juniperCommunity";
export const PERMISSION_SET =
  "net.sp00ky.juniper-pds.authority.juniperPermissions";
export const POST_COLLECTION =
  "net.sp00ky.juniper-pds.authority.juniperPost";
export const SUBMISSION_COLLECTION =
  "net.sp00ky.juniper-pds.authority.juniperSubmission";
export const ADMISSION_COLLECTION =
  "net.sp00ky.juniper-pds.authority.juniperAdmission";
export const REMOVAL_COLLECTION =
  "net.sp00ky.juniper-pds.authority.juniperRemoval";
export const WITHDRAWAL_COLLECTION =
  "net.sp00ky.juniper-pds.authority.juniperWithdrawal";
export const CONSENT_PROFILE = "scv0-exact-public-presentation-consent/1";

export const OAUTH_SCOPE = ["atproto", `include:${PERMISSION_SET}`].join(" ");
