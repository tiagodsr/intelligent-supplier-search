# TFLint configuration, used by pre-commit and CI once Terraform code exists under infrastructure/.
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
