// ci-cd/jenkins/Jenkinsfile

pipeline {
    agent any
    
    environment {
        DOCKER_REGISTRY = 'docker.io'
        DOCKER_IMAGE = 'your-username/devops-automation-backend'
        AWS_REGION = 'us-east-1'
        AWS_ACCOUNT_ID = credentials('aws-account-id')
        SLACK_CHANNEL = '#devops-notifications'
        APP_VERSION = "${BUILD_NUMBER}"
    }
    
    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
    }
    
    stages {
        stage('Checkout') {
            steps {
                script {
                    echo "🔄 Checking out code from repository..."
                    checkout scm
                }
            }
        }
        
        stage('Environment Info') {
            steps {
                script {
                    echo "📋 Build Information:"
                    sh '''
                        echo "Build Number: ${BUILD_NUMBER}"
                        echo "Job Name: ${JOB_NAME}"
                        echo "Node Version: $(node --version)"
                        echo "NPM Version: $(npm --version)"
                        echo "Docker Version: $(docker --version)"
                        echo "Git Commit: $(git rev-parse --short HEAD)"
                    '''
                }
            }
        }
        
        stage('Install Dependencies') {
            steps {
                dir('app/backend') {
                    script {
                        echo "📦 Installing dependencies..."
                        sh 'npm ci'
                    }
                }
            }
        }
        
        stage('Lint') {
            steps {
                dir('app/backend') {
                    script {
                        echo "🔍 Running linter..."
                        sh 'npm run lint || true'
                    }
                }
            }
        }
        
        stage('Unit Tests') {
            steps {
                dir('app/backend') {
                    script {
                        echo "🧪 Running unit tests..."
                        sh 'npm test -- --coverage'
                    }
                }
            }
            post {
                always {
                    junit '**/test-results/*.xml'
                    publishHTML(target: [
                        allowMissing: false,
                        alwaysLinkToLastBuild: true,
                        keepAll: true,
                        reportDir: 'app/backend/coverage',
                        reportFiles: 'index.html',
                        reportName: 'Coverage Report'
                    ])
                }
            }
        }
        
        stage('Security Scan') {
            steps {
                dir('app/backend') {
                    script {
                        echo "🔒 Running security scan..."
                        sh 'npm audit --audit-level=moderate || true'
                    }
                }
            }
        }
        
        stage('Build Docker Image') {
            steps {
                dir('app/backend') {
                    script {
                        echo "🐳 Building Docker image..."
                        docker.build("${DOCKER_IMAGE}:${BUILD_NUMBER}")
                        docker.build("${DOCKER_IMAGE}:latest")
                    }
                }
            }
        }
        
        stage('Docker Image Scan') {
            steps {
                script {
                    echo "🔍 Scanning Docker image for vulnerabilities..."
                    sh """
                        docker run --rm \
                            -v /var/run/docker.sock:/var/run/docker.sock \
                            aquasec/trivy:latest \
                            image --severity HIGH,CRITICAL \
                            ${DOCKER_IMAGE}:${BUILD_NUMBER} || true
                    """
                }
            }
        }
        
        stage('Push to Registry') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "📤 Pushing Docker image to registry..."
                    docker.withRegistry("https://${DOCKER_REGISTRY}", 'dockerhub-credentials') {
                        docker.image("${DOCKER_IMAGE}:${BUILD_NUMBER}").push()
                        docker.image("${DOCKER_IMAGE}:latest").push()
                    }
                }
            }
        }
        
        stage('Upload Artifacts') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "☁️ Uploading artifacts to S3..."
                    sh """
                        aws s3 cp app/backend/package.json \
                            s3://prod-devops-artifacts-${AWS_ACCOUNT_ID}/builds/${BUILD_NUMBER}/ \
                            --region ${AWS_REGION}
                    """
                }
            }
        }
        
        stage('Terraform Plan') {
            when {
                branch 'main'
            }
            steps {
                dir('infrastructure/terraform') {
                    script {
                        echo "📋 Planning infrastructure changes..."
                        sh '''
                            terraform init -upgrade
                            terraform plan -out=tfplan \
                                -var="docker_image=${DOCKER_IMAGE}:${BUILD_NUMBER}"
                        '''
                    }
                }
            }
        }
        
        stage('Deploy to Staging') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "🚀 Deploying to staging environment..."
                    input message: 'Deploy to Staging?', ok: 'Deploy'
                    
                    sh """
                        python3 scripts/deploy.py \
                            --environment staging \
                            --version ${BUILD_NUMBER} \
                            --image ${DOCKER_IMAGE}:${BUILD_NUMBER}
                    """
                }
            }
        }
        
        stage('Integration Tests') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "🧪 Running integration tests..."
                    sh """
                        python3 scripts/health_check.py \
                            --url http://staging-alb-url/health \
                            --timeout 300
                    """
                }
            }
        }
        
        stage('Deploy to Production') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "🚀 Deploying to production environment..."
                    input message: 'Deploy to Production?', ok: 'Deploy'
                    
                    sh """
                        python3 scripts/deploy.py \
                            --environment production \
                            --version ${BUILD_NUMBER} \
                            --image ${DOCKER_IMAGE}:${BUILD_NUMBER}
                    """
                }
            }
        }
        
        stage('Verify Deployment') {
            when {
                branch 'main'
            }
            steps {
                script {
                    echo "✅ Verifying deployment..."
                    sh """
                        python3 scripts/health_check.py \
                            --url http://prod-alb-url/health \
                            --timeout 300
                    """
                }
            }
        }
    }
    
    post {
        success {
            script {
                echo "✅ Pipeline completed successfully!"
                // slackSend(
                //     channel: SLACK_CHANNEL,
                //     color: 'good',
                //     message: "✅ Build #${BUILD_NUMBER} succeeded for ${JOB_NAME}"
                // )
            }
        }
        
        failure {
            script {
                echo "❌ Pipeline failed!"
                // slackSend(
                //     channel: SLACK_CHANNEL,
                //     color: 'danger',
                //     message: "❌ Build #${BUILD_NUMBER} failed for ${JOB_NAME}"
                // )
                
                // Rollback on failure
                sh """
                    python3 scripts/rollback.py \
                        --environment production \
                        --previous-version \${BUILD_NUMBER - 1}
                """
            }
        }
        
        always {
            script {
                echo "🧹 Cleaning up..."
                sh 'docker system prune -f'
                cleanWs()
            }
        }
    }
}