#!/usr/bin/env python3
# scripts/deploy.py

import argparse
import boto3
import time
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DeploymentManager:
    def __init__(self, environment, region='us-east-1'):
        self.environment = environment
        self.region = region
        self.autoscaling = boto3.client('autoscaling', region_name=region)
        self.ec2 = boto3.client('ec2', region_name=region)
        self.elb = boto3.client('elbv2', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
        
    def get_asg_name(self):
        """Get Auto Scaling Group name for environment"""
        asg_name = f"{self.environment}-asg"
        logger.info(f"Using ASG: {asg_name}")
        return asg_name
    
    def update_launch_template(self, image):
        """Update launch template with new Docker image"""
        logger.info(f"Updating launch template with image: {image}")
        
        # Get current launch template
        asg_name = self.get_asg_name()
        response = self.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            logger.error(f"ASG {asg_name} not found")
            return False
        
        asg = response['AutoScalingGroups'][0]
        lt_id = asg['LaunchTemplate']['LaunchTemplateId']
        
        # Create new version with updated user data
        user_data = self._generate_user_data(image)
        
        response = self.ec2.create_launch_template_version(
            LaunchTemplateId=lt_id,
            SourceVersion='$Latest',
            LaunchTemplateData={
                'UserData': user_data
            }
        )
        
        new_version = response['LaunchTemplateVersion']['VersionNumber']
        logger.info(f"Created launch template version: {new_version}")
        
        # Update ASG to use new version
        self.autoscaling.update_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            LaunchTemplate={
                'LaunchTemplateId': lt_id,
                'Version': str(new_version)
            }
        )
        
        return True
    
    def _generate_user_data(self, image):
        """Generate user data script for EC2 instances"""
        import base64
        
        script = f"""#!/bin/bash
set -e

# Pull new image
docker pull {image}

# Stop old container
docker stop app || true
docker rm app || true

# Run new container
docker run -d \\
  --name app \\
  --restart unless-stopped \\
  -p 3000:3000 \\
  -e NODE_ENV={self.environment} \\
  {image}

# Wait for health check
for i in {{1..30}}; do
  if curl -f http://localhost:3000/health > /dev/null 2>&1; then
    echo "Application is healthy!"
    exit 0
  fi
  sleep 2
done

echo "Application failed to start"
exit 1
"""
        return base64.b64encode(script.encode()).decode()
    
    def rolling_deployment(self, image):
        """Perform rolling deployment"""
        logger.info(f"Starting rolling deployment for {self.environment}")
        
        # Update launch template
        if not self.update_launch_template(image):
            logger.error("Failed to update launch template")
            return False
        
        # Start instance refresh
        asg_name = self.get_asg_name()
        logger.info(f"Starting instance refresh for {asg_name}")
        
        response = self.autoscaling.start_instance_refresh(
            AutoScalingGroupName=asg_name,
            Strategy='Rolling',
            Preferences={
                'MinHealthyPercentage': 50,
                'InstanceWarmup': 300
            }
        )
        
        refresh_id = response['InstanceRefreshId']
        logger.info(f"Instance refresh started: {refresh_id}")
        
        # Monitor refresh progress
        return self.monitor_refresh(asg_name, refresh_id)
    
    def monitor_refresh(self, asg_name, refresh_id):
        """Monitor instance refresh progress"""
        logger.info("Monitoring instance refresh...")
        
        while True:
            response = self.autoscaling.describe_instance_refreshes(
                AutoScalingGroupName=asg_name,
                InstanceRefreshIds=[refresh_id]
            )
            
            if not response['InstanceRefreshes']:
                logger.error("Instance refresh not found")
                return False
            
            refresh = response['InstanceRefreshes'][0]
            status = refresh['Status']
            
            if status == 'Successful':
                logger.info("✅ Instance refresh completed successfully")
                return True
            elif status in ['Cancelled', 'Failed']:
                logger.error(f"❌ Instance refresh {status}")
                return False
            else:
                percentage = refresh.get('PercentageComplete', 0)
                logger.info(f"⏳ Instance refresh in progress: {percentage}%")
                time.sleep(30)
    
    def verify_deployment(self, target_group_arn):
        """Verify all instances are healthy"""
        logger.info("Verifying deployment health...")
        
        max_attempts = 20
        for attempt in range(max_attempts):
            response = self.elb.describe_target_health(
                TargetGroupArn=target_group_arn
            )
            
            total = len(response['TargetHealthDescriptions'])
            healthy = sum(1 for t in response['TargetHealthDescriptions'] 
                         if t['TargetHealth']['State'] == 'healthy')
            
            logger.info(f"Healthy targets: {healthy}/{total}")
            
            if healthy == total and total > 0:
                logger.info("✅ All targets are healthy")
                return True
            
            if attempt < max_attempts - 1:
                time.sleep(15)
        
        logger.error("❌ Not all targets became healthy")
        return False
    
    def create_deployment_record(self, version, image, status):
        """Record deployment in S3"""
        bucket = f"{self.environment}-devops-artifacts"
        key = f"deployments/{datetime.now().isoformat()}.json"
        
        record = {
            'timestamp': datetime.now().isoformat(),
            'environment': self.environment,
            'version': version,
            'image': image,
            'status': status
        }
        
        import json
        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(record, indent=2)
        )
        
        logger.info(f"Deployment record saved to s3://{bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description='Deploy application')
    parser.add_argument('--environment', required=True, 
                       choices=['dev', 'staging', 'production'],
                       help='Target environment')
    parser.add_argument('--version', required=True, 
                       help='Application version')
    parser.add_argument('--image', required=True, 
                       help='Docker image with tag')
    parser.add_argument('--region', default='us-east-1', 
                       help='AWS region')
    
    args = parser.parse_args()
    
    logger.info(f"🚀 Starting deployment to {args.environment}")
    logger.info(f"Version: {args.version}")
    logger.info(f"Image: {args.image}")
    
    deployer = DeploymentManager(args.environment, args.region)
    
    try:
        # Perform rolling deployment
        success = deployer.rolling_deployment(args.image)
        
        if success:
            # Record successful deployment
            deployer.create_deployment_record(
                args.version, args.image, 'success'
            )
            logger.info("✅ Deployment completed successfully")
            sys.exit(0)
        else:
            # Record failed deployment
            deployer.create_deployment_record(
                args.version, args.image, 'failed'
            )
            logger.error("❌ Deployment failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"❌ Deployment error: {str(e)}")
        deployer.create_deployment_record(
            args.version, args.image, 'error'
        )
        sys.exit(1)


if __name__ == '__main__':
    main()