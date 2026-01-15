#!/usr/bin/env python3
# scripts/rollback.py

import argparse
import boto3
import json
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RollbackManager:
    def __init__(self, environment, region='us-east-1'):
        self.environment = environment
        self.region = region
        self.autoscaling = boto3.client('autoscaling', region_name=region)
        self.ec2 = boto3.client('ec2', region_name=region)
        self.s3 = boto3.client('s3', region_name=region)
    
    def get_deployment_history(self, limit=10):
        """Retrieve deployment history from S3"""
        bucket = f"{self.environment}-devops-artifacts"
        prefix = "deployments/"
        
        try:
            response = self.s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=limit
            )
            
            if 'Contents' not in response:
                logger.warning("No deployment history found")
                return []
            
            # Sort by last modified (most recent first)
            objects = sorted(
                response['Contents'], 
                key=lambda x: x['LastModified'], 
                reverse=True
            )
            
            deployments = []
            for obj in objects:
                try:
                    response = self.s3.get_object(
                        Bucket=bucket,
                        Key=obj['Key']
                    )
                    data = json.loads(response['Body'].read())
                    deployments.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read {obj['Key']}: {e}")
            
            return deployments
            
        except Exception as e:
            logger.error(f"Failed to retrieve deployment history: {e}")
            return []
    
    def find_previous_successful_deployment(self):
        """Find the most recent successful deployment"""
        history = self.get_deployment_history(limit=20)
        
        for deployment in history:
            if deployment.get('status') == 'success':
                logger.info(f"Found previous successful deployment:")
                logger.info(f"  Version: {deployment['version']}")
                logger.info(f"  Image: {deployment['image']}")
                logger.info(f"  Timestamp: {deployment['timestamp']}")
                return deployment
        
        logger.error("No successful deployment found in history")
        return None
    
    def rollback_to_version(self, target_version=None, target_image=None):
        """Rollback to a specific version or previous successful deployment"""
        logger.info(f"🔄 Starting rollback for {self.environment}")
        
        if not target_version and not target_image:
            # Find previous successful deployment
            deployment = self.find_previous_successful_deployment()
            if not deployment:
                return False
            
            target_version = deployment['version']
            target_image = deployment['image']
        
        logger.info(f"Rolling back to version {target_version}")
        logger.info(f"Image: {target_image}")
        
        # Get ASG and launch template info
        asg_name = f"{self.environment}-asg"
        response = self.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[asg_name]
        )
        
        if not response['AutoScalingGroups']:
            logger.error(f"ASG {asg_name} not found")
            return False
        
        asg = response['AutoScalingGroups'][0]
        lt_id = asg['LaunchTemplate']['LaunchTemplateId']
        
        # Get launch template versions
        lt_versions = self.get_launch_template_versions(lt_id)
        
        # Find version with matching image
        target_lt_version = self.find_matching_launch_template(
            lt_versions, target_image
        )
        
        if not target_lt_version:
            logger.warning("Matching launch template version not found")
            logger.info("Creating new version with target image...")
            target_lt_version = self.create_rollback_version(
                lt_id, target_image
            )
        
        # Update ASG to use target version
        logger.info(f"Updating ASG to use launch template version {target_lt_version}")
        self.autoscaling.update_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            LaunchTemplate={
                'LaunchTemplateId': lt_id,
                'Version': str(target_lt_version)
            }
        )
        
        # Start instance refresh
        logger.info("Starting instance refresh for rollback...")
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
        
        # Monitor refresh
        success = self.monitor_refresh(asg_name, refresh_id)
        
        if success:
            # Record rollback
            self.record_rollback(target_version, target_image)
            logger.info("✅ Rollback completed successfully")
        else:
            logger.error("❌ Rollback failed")
        
        return success
    
    def get_launch_template_versions(self, lt_id):
        """Get all versions of a launch template"""
        response = self.ec2.describe_launch_template_versions(
            LaunchTemplateId=lt_id,
            MaxResults=100
        )
        return response['LaunchTemplateVersions']
    
    def find_matching_launch_template(self, versions, target_image):
        """Find launch template version with matching image"""
        for version in versions:
            user_data = version.get('LaunchTemplateData', {}).get('UserData', '')
            if target_image in user_data:
                return version['VersionNumber']
        return None
    
    def create_rollback_version(self, lt_id, target_image):
        """Create new launch template version for rollback"""
        import base64
        
        script = f"""#!/bin/bash
set -e
docker pull {target_image}
docker stop app || true
docker rm app || true
docker run -d \\
  --name app \\
  --restart unless-stopped \\
  -p 3000:3000 \\
  -e NODE_ENV={self.environment} \\
  {target_image}
"""
        
        user_data = base64.b64encode(script.encode()).decode()
        
        response = self.ec2.create_launch_template_version(
            LaunchTemplateId=lt_id,
            LaunchTemplateData={
                'UserData': user_data
            }
        )
        
        return response['LaunchTemplateVersion']['VersionNumber']
    
    def monitor_refresh(self, asg_name, refresh_id):
        """Monitor instance refresh progress"""
        import time
        
        while True:
            response = self.autoscaling.describe_instance_refreshes(
                AutoScalingGroupName=asg_name,
                InstanceRefreshIds=[refresh_id]
            )
            
            if not response['InstanceRefreshes']:
                return False
            
            refresh = response['InstanceRefreshes'][0]
            status = refresh['Status']
            
            if status == 'Successful':
                return True
            elif status in ['Cancelled', 'Failed']:
                return False
            else:
                percentage = refresh.get('PercentageComplete', 0)
                logger.info(f"⏳ Rollback in progress: {percentage}%")
                time.sleep(30)
    
    def record_rollback(self, version, image):
        """Record rollback operation"""
        bucket = f"{self.environment}-devops-artifacts"
        key = f"rollbacks/{datetime.now().isoformat()}.json"
        
        record = {
            'timestamp': datetime.now().isoformat(),
            'environment': self.environment,
            'action': 'rollback',
            'target_version': version,
            'target_image': image
        }
        
        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(record, indent=2)
        )
        
        logger.info(f"Rollback record saved to s3://{bucket}/{key}")


def main():
    parser = argparse.ArgumentParser(description='Rollback deployment')
    parser.add_argument('--environment', required=True,
                       choices=['dev', 'staging', 'production'],
                       help='Target environment')
    parser.add_argument('--previous-version', type=int,
                       help='Specific version to rollback to')
    parser.add_argument('--image',
                       help='Specific Docker image to rollback to')
    parser.add_argument('--region', default='us-east-1',
                       help='AWS region')
    
    args = parser.parse_args()
    
    logger.info(f"🔄 Initiating rollback for {args.environment}")
    
    manager = RollbackManager(args.environment, args.region)
    
    try:
        success = manager.rollback_to_version(
            args.previous_version, 
            args.image
        )
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Rollback error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()