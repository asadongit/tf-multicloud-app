
variable "instance_type" {
  type        = string
  description = "The EC2 instance type"
  default     = "t2.micro"
}

variable "tags" {
  type = map(string)
}

variable "instance_count" {
    type = number
    default = 1
}
